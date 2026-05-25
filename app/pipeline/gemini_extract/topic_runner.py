"""Manual Topic extraction runner for future API integration.

This module is used by ``topic_service`` for real Topic extraction.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from app.pipeline.gemini_extract.offset_detector import detect_page_offset
from app.pipeline.gemini_extract.pdf_utils import (
    count_pdf_pages,
    create_front_matter_pdf,
    split_topics_and_lessons,
)
from app.pipeline.gemini_extract.prompts.topic_lesson_prompt import (
    build_topic_lesson_prompt,
)
from app.pipeline.gemini_extract.topic_parser import (
    normalize_topic_lesson_payload,
    parse_json_loose,
)
from app.services.gemini.client import generate_with_pdf


def run_topic_extraction(
    pdf_path: str | Path,
    model: str | None = None,
    offset: int | str | None = "auto",
    split_pdf: bool = False,
    output_root: str | Path | None = None,
    auto_detect_offset: bool = True,
    offset_detection_min_confidence: float = 0.65,
    use_front_matter: bool = True,
    front_matter_start_page: int = 1,
    front_matter_end_page: int = 12,
    fallback_to_full_pdf: bool = True,
) -> dict[str, Any]:
    path = _validate_pdf_path(pdf_path)

    if split_pdf and output_root is None:
        raise ValueError("output_root is required when split_pdf=True")

    offset_mode = _parse_offset_mode(offset)
    total_pages = count_pdf_pages(path)
    prompt = build_topic_lesson_prompt()
    front_matter_pdf_path = None
    fallback_used = False

    if use_front_matter:
        front_matter_pdf_path = _front_matter_path(
            source_pdf=path,
            output_root=output_root,
        )
        create_front_matter_pdf(
            source_pdf=path,
            output_pdf=front_matter_pdf_path,
            start_page=front_matter_start_page,
            end_page=front_matter_end_page,
        )

        try:
            raw_response_text, payload = _extract_payload_with_gemini(
                prompt=prompt,
                pdf_path=front_matter_pdf_path,
                model=model,
            )
            extraction_input = "front_matter"

            if not _payload_has_structure(payload):
                raise ValueError("Front-matter Gemini response has no topics or lessons.")

        except Exception as exc:
            if not fallback_to_full_pdf:
                raise ValueError(f"Front-matter Topic extraction failed: {exc}") from exc

            fallback_used = True
            raw_response_text, payload = _extract_payload_with_gemini(
                prompt=prompt,
                pdf_path=path,
                model=model,
            )
            extraction_input = "full_pdf"

            if not _payload_has_structure(payload):
                raise ValueError("Full-PDF Gemini response has no topics or lessons.")

    else:
        raw_response_text, payload = _extract_payload_with_gemini(
            prompt=prompt,
            pdf_path=path,
            model=model,
        )
        extraction_input = "full_pdf"

        if not _payload_has_structure(payload):
            raise ValueError("Full-PDF Gemini response has no topics or lessons.")

    offset_detection = None
    effective_offset: int | None = None

    if isinstance(offset_mode, int):
        effective_offset = offset_mode
    elif offset_mode == "auto":
        if auto_detect_offset:
            initial_normalized = normalize_topic_lesson_payload(
                payload,
                total_pdf_pages=total_pages,
                offset=None,
            )
            offset_detection = detect_page_offset(
                source_pdf=path,
                topics=initial_normalized["topics"],
                model=model,
                min_confidence=offset_detection_min_confidence,
            )

            if offset_detection.get("detected") is True:
                effective_offset = int(offset_detection["offset"])
        else:
            offset_detection = {
                "detected": False,
                "offset": None,
                "reason": "Automatic offset detection is disabled.",
                "best_candidate": None,
                "candidates": [],
            }

    normalized = normalize_topic_lesson_payload(
        payload,
        total_pdf_pages=total_pages,
        offset=effective_offset,
    )

    topics = normalized["topics"]
    lessons = normalized["lessons"]
    split_result = None

    if split_pdf:
        _ensure_items_can_split(topics, lessons)
        split_result = split_topics_and_lessons(
            source_pdf=path,
            output_root=Path(output_root),
            topics=topics,
            lessons=lessons,
        )

    return {
        "source": "gemini",
        "pdf_path": str(path),
        "total_pdf_pages": total_pages,
        "extraction_input": extraction_input,
        "front_matter_pdf_path": str(front_matter_pdf_path) if front_matter_pdf_path else None,
        "fallback_used": fallback_used,
        "offset": effective_offset,
        "offset_detection": offset_detection,
        "topics": topics,
        "lessons": lessons,
        "raw_response_text": raw_response_text,
        "raw_payload": normalized["raw_payload"],
        "split_result": split_result,
    }


def _extract_payload_with_gemini(
    *,
    prompt: str,
    pdf_path: Path,
    model: str | None,
) -> tuple[str, dict[str, Any]]:
    raw_response_text = generate_with_pdf(
        prompt=prompt,
        pdf_path=pdf_path,
        model=model,
    )

    try:
        payload = parse_json_loose(raw_response_text)
    except ValueError as exc:
        raise ValueError(f"Failed to parse Gemini Topic response: {exc}") from exc

    return raw_response_text, payload


def _payload_has_structure(payload: dict[str, Any]) -> bool:
    topics = payload.get("topics")
    lessons = payload.get("lessons")
    return bool(topics) and bool(lessons)


def _front_matter_path(
    *,
    source_pdf: Path,
    output_root: str | Path | None,
) -> Path:
    if output_root is not None:
        return Path(output_root) / "topic" / "front_matter.pdf"

    temp_dir = Path(tempfile.gettempdir()) / "ai_extract"
    return temp_dir / f"{source_pdf.stem}_front_matter.pdf"


def _parse_offset_mode(offset: int | str | None) -> int | str | None:
    if offset is None:
        return None

    if isinstance(offset, int):
        return offset

    value = str(offset).strip().lower()

    if value in {"", "none", "null"}:
        return None

    if value == "auto":
        return "auto"

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("offset must be 'auto', 'none', None, or an integer") from exc


def _ensure_items_can_split(topics: list[dict], lessons: list[dict]) -> None:
    missing = [
        item.get("name") or "<unnamed>"
        for item in [*topics, *lessons]
        if item.get("start") is None or item.get("end") is None
    ]

    if missing:
        raise ValueError(
            "Cannot split PDF because some topics/lessons do not have actual "
            f"PDF start/end pages. Missing ranges: {missing}"
        )


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    path = Path(pdf_path)

    if not path.exists():
        raise ValueError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF file must have a .pdf extension: {path}")

    return path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run manual Gemini Topic/Lesson extraction for a PDF.",
    )
    parser.add_argument("--pdf", required=True, help="Path to source PDF.")
    parser.add_argument("--model", default=None, help="Optional Gemini model name.")
    parser.add_argument(
        "--offset",
        default="auto",
        help="Offset mode: auto, none, or an integer value.",
    )
    parser.add_argument(
        "--split-pdf",
        action="store_true",
        help="Split normalized topics/lessons into PDF files.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Output root for split PDFs when --split-pdf is used.",
    )
    return parser.parse_args()


def _main() -> None:
    args = _parse_args()
    result = run_topic_extraction(
        pdf_path=args.pdf,
        model=args.model,
        offset=args.offset,
        split_pdf=args.split_pdf,
        output_root=args.output_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
