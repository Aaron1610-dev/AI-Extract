"""OCR-based printed-page to PDF-page offset detection."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image


_BOTTOM_CROP_PX = 250
_OCR_SCALES = (3, 4, 5)
_OCR_PSMS = (6, 7, 8, 10, 13)


def detect_page_offset(
    source_pdf: str | Path,
    topics: list[dict] | None = None,
    model: str | None = None,
    candidate_window_before: int = 8,
    candidate_window_after: int = 12,
    min_confidence: float = 0.65,
    temp_dir: str | Path | None = None,
    use_gemini_fallback: bool = False,
) -> dict[str, Any]:
    del topics, model, candidate_window_before, candidate_window_after
    del min_confidence, temp_dir

    if use_gemini_fallback:
        raise ValueError("Gemini fallback for offset detection is disabled.")

    return detect_page_offset_by_bottom_ocr(source_pdf=source_pdf)


def detect_page_offset_by_bottom_ocr(
    source_pdf: str | Path,
    anchor_page: int = 28,
    pages_per_round: int = 3,
    min_majority: int = 2,
    max_rounds: int = 5,
    dpi: int = 250,
    crop_px: int = _BOTTOM_CROP_PX,
    max_abs_offset: int = 5,
    save_debug: bool = False,
    debug_dir: str | Path | None = None,
) -> dict[str, Any]:
    source_path = _validate_pdf_path(source_pdf)

    if anchor_page < 1:
        raise ValueError("anchor_page must be greater than 0")

    if pages_per_round < 1:
        raise ValueError("pages_per_round must be greater than 0")

    if min_majority < 1:
        raise ValueError("min_majority must be greater than 0")

    if max_rounds < 1:
        raise ValueError("max_rounds must be greater than 0")

    if dpi < 72:
        raise ValueError("dpi must be at least 72")

    if crop_px < 1:
        raise ValueError("crop_px must be greater than 0")

    if max_abs_offset < 0:
        raise ValueError("max_abs_offset must be non-negative")

    total_pages = _count_pdf_pages(source_path)
    current_start = anchor_page
    pages_checked: list[int] = []
    valid_votes: list[dict[str, int]] = []
    offset_counter: Counter[int] = Counter()

    debug_root = Path(debug_dir) if save_debug and debug_dir else None
    if debug_root:
        debug_root.mkdir(parents=True, exist_ok=True)

    for round_index in range(1, max_rounds + 1):
        pages = [
            page
            for page in range(current_start, current_start + pages_per_round)
            if 1 <= page <= total_pages
        ]

        for actual_page in pages:
            pages_checked.append(actual_page)
            page_debug_dir = (
                debug_root / f"round_{round_index}" / f"page_{actual_page}"
                if debug_root
                else None
            )

            page_result = detect_offset_for_one_page(
                source_pdf=source_path,
                actual_page=actual_page,
                dpi=dpi,
                crop_px=crop_px,
                max_abs_offset=max_abs_offset,
                save_debug=save_debug,
                debug_dir=page_debug_dir,
            )

            if not page_result.get("detected"):
                continue

            vote = {
                "actual_page": actual_page,
                "printed_page": int(page_result["printed_page"]),
                "offset": int(page_result["offset"]),
            }
            valid_votes.append(vote)
            offset_counter[vote["offset"]] += 1

            if offset_counter[vote["offset"]] >= min_majority:
                best_offset = vote["offset"]
                matched_votes = [
                    item for item in valid_votes
                    if item["offset"] == best_offset
                ]

                return {
                    "detected": True,
                    "strategy": "bottom_ocr_cumulative_vote",
                    "offset": best_offset,
                    "formula": "actual_page = printed_page + offset",
                    "anchor_page": anchor_page,
                    "round_detected": round_index,
                    "vote_count": offset_counter[best_offset],
                    "required_majority": min_majority,
                    "pages_checked": pages_checked,
                    "matched_votes": matched_votes,
                    "valid_votes": valid_votes,
                }

        current_start += pages_per_round

    if valid_votes:
        best_overall_offset, best_overall_count = offset_counter.most_common(1)[0]
        return {
            "detected": False,
            "strategy": "bottom_ocr_cumulative_vote",
            "offset": None,
            "reason": "No offset reached required cumulative majority.",
            "best_overall_offset": best_overall_offset,
            "best_overall_vote_count": best_overall_count,
            "required_majority": min_majority,
            "pages_checked": pages_checked,
            "valid_votes": valid_votes,
        }

    return {
        "detected": False,
        "strategy": "bottom_ocr_cumulative_vote",
        "offset": None,
        "reason": "No valid printed page numbers detected.",
        "best_overall_offset": None,
        "best_overall_vote_count": 0,
        "required_majority": min_majority,
        "pages_checked": pages_checked,
        "valid_votes": valid_votes,
    }


def render_bottom_crop(
    source_pdf: str | Path,
    page_number: int,
    dpi: int = 250,
    crop_px: int = _BOTTOM_CROP_PX,
) -> Image.Image:
    source_path = _validate_pdf_path(source_pdf)

    doc = fitz.open(source_path)
    try:
        total_pages = len(doc)

        if page_number < 1 or page_number > total_pages:
            raise ValueError(
                f"page_number={page_number} is outside PDF page count {total_pages}"
            )

        page = doc[page_number - 1]
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        width, height = image.size
        crop_px = max(1, min(crop_px, height))
        return image.crop((0, height - crop_px, width, height))

    finally:
        doc.close()


def preprocess_variants(image: Image.Image) -> list[tuple[str, np.ndarray]]:
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    variants: list[tuple[str, np.ndarray]] = []

    for scale in _OCR_SCALES:
        resized = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        blur = cv2.GaussianBlur(resized, (3, 3), 0)

        _, otsu = cv2.threshold(
            blur,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        variants.append((f"scale_{scale}_otsu", otsu))

        _, otsu_inv = cv2.threshold(
            blur,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )
        variants.append((f"scale_{scale}_otsu_inv", otsu_inv))

        adaptive = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        variants.append((f"scale_{scale}_adaptive", adaptive))

    return variants


def extract_numbers(text: str) -> list[int]:
    numbers: list[int] = []

    for raw in re.findall(r"\d{1,3}", text or ""):
        number = int(raw)
        if 1 <= number <= 300:
            numbers.append(number)

    return numbers


def detect_offset_for_one_page(
    source_pdf: str | Path,
    actual_page: int,
    dpi: int = 250,
    crop_px: int = _BOTTOM_CROP_PX,
    max_abs_offset: int = 5,
    save_debug: bool = False,
    debug_dir: str | Path | None = None,
) -> dict[str, Any]:
    bottom_crop = render_bottom_crop(
        source_pdf=source_pdf,
        page_number=actual_page,
        dpi=dpi,
        crop_px=crop_px,
    )

    debug_path = Path(debug_dir) if save_debug and debug_dir else None
    if debug_path:
        debug_path.mkdir(parents=True, exist_ok=True)
        bottom_crop.save(debug_path / f"page_{actual_page}_bottom_{crop_px}px.png")

    valid_numbers: list[int] = []
    valid_offsets: list[int] = []

    for variant_name, variant_img in preprocess_variants(bottom_crop):
        if debug_path:
            cv2.imwrite(str(debug_path / f"{variant_name}.png"), variant_img)

        for psm in _OCR_PSMS:
            raw_text = pytesseract.image_to_string(
                variant_img,
                config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
            ).strip()

            for number in extract_numbers(raw_text):
                offset = actual_page - number

                if abs(offset) <= max_abs_offset:
                    valid_numbers.append(number)
                    valid_offsets.append(offset)

    if not valid_offsets:
        return {
            "detected": False,
            "actual_page": actual_page,
            "printed_page": None,
            "offset": None,
            "reason": "OCR did not produce any reasonable page number.",
        }

    offset_counter = Counter(valid_offsets)
    best_offset, best_offset_count = offset_counter.most_common(1)[0]
    number_counter = Counter(valid_numbers)
    best_number, best_number_count = number_counter.most_common(1)[0]

    return {
        "detected": True,
        "actual_page": actual_page,
        "printed_page": best_number,
        "offset": best_offset,
        "formula": "actual_page = printed_page + offset",
        "best_number_vote_count": best_number_count,
        "best_offset_vote_count": best_offset_count,
    }


def _validate_pdf_path(source_pdf: str | Path) -> Path:
    path = Path(source_pdf)

    if not path.exists():
        raise ValueError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF file must have a .pdf extension: {path}")

    return path


def _count_pdf_pages(source_pdf: Path) -> int:
    doc = fitz.open(source_pdf)
    try:
        return len(doc)
    finally:
        doc.close()
