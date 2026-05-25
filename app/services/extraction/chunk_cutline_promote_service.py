from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.schemas.extraction import ChunkCutlinePromoteResponse
from app.services.extraction.job_service import get_job
from app.services.storage.workspace_service import (
    get_chunk_cutline_json_path,
    get_chunk_cutline_page_image_path,
    get_chunk_cutline_promote_json_path,
    get_chunk_doc_backup_pdf_path,
    get_chunk_json_path,
    get_chunk_pdf_path,
    get_lesson_doc_path,
    read_json,
    write_json,
)


MIN_MATCH_REQUIRED = 3


class ChunkCutlinePromoteInputError(ValueError):
    pass


def promote_cutline_for_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> ChunkCutlinePromoteResponse:
    get_job(job_id)

    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    selected_chunk_path = get_chunk_json_path(job_id, lesson_name, chunk_name)
    if not selected_chunk_path.exists():
        raise FileNotFoundError(f"Chunk JSON was not found: {selected_chunk_path}")

    cutline_json_path = get_chunk_cutline_json_path(job_id, lesson_name, chunk_name)
    if not cutline_json_path.exists():
        raise FileNotFoundError(f"Cutline JSON was not found: {cutline_json_path}")

    selected_chunk = _read_object(selected_chunk_path, "selected chunk")
    cutline = _read_object(cutline_json_path, "cutline result")

    if not bool(cutline.get("matched")):
        raise ChunkCutlinePromoteInputError("Cutline result must have matched=true.")

    y_cut = _required_number(cutline, "y_cut")
    selected_start = _required_int(selected_chunk, "start")
    selected_end = _required_int(selected_chunk, "end")
    page_number = _required_int(cutline, "page_number")

    if page_number != selected_start:
        raise ChunkCutlinePromoteInputError(
            f"Cutline page_number={page_number} does not match selected chunk start={selected_start}."
        )

    _validate_cutline_confidence(cutline)

    image_height = _get_image_height(
        cutline=cutline,
        page_image_path=get_chunk_cutline_page_image_path(job_id, lesson_name, chunk_name),
    )

    selected_output_path = get_chunk_pdf_path(job_id, lesson_name, chunk_name)
    selected_backup_path: Path | None = None

    previous_chunk_name: str | None = None
    previous_output_path: Path | None = None
    previous_backup_path: Path | None = None
    previous_start: int | None = None

    if _is_first_chunk(chunk_name=chunk_name, selected_chunk=selected_chunk):
        selected_backup_path = _backup_official_pdf(
            source_path=selected_output_path,
            backup_path=get_chunk_doc_backup_pdf_path(job_id, lesson_name, chunk_name),
        )
        metrics = _write_selected_official_pdf(
            source_pdf=lesson_pdf_path,
            selected_output_pdf=selected_output_path,
            selected_start=selected_start,
            selected_end=selected_end,
            y_cut_image=float(y_cut),
            image_height=float(image_height),
        )
    else:
        if not bool(selected_chunk.get("content_head")):
            raise ChunkCutlinePromoteInputError(
                "Selected chunk does not have content_head=true; official page-range doc is already sufficient."
            )

        previous_chunk_name = _previous_chunk_name(chunk_name)
        previous_chunk_path = get_chunk_json_path(job_id, lesson_name, previous_chunk_name)
        if not previous_chunk_path.exists():
            raise FileNotFoundError(f"Previous chunk JSON was not found: {previous_chunk_path}")

        previous_chunk = _read_object(previous_chunk_path, "previous chunk")
        previous_start = _required_int(previous_chunk, "start")
        previous_output_path = get_chunk_pdf_path(job_id, lesson_name, previous_chunk_name)
        selected_backup_path = _backup_official_pdf(
            source_path=selected_output_path,
            backup_path=get_chunk_doc_backup_pdf_path(job_id, lesson_name, chunk_name),
        )
        previous_backup_path = _backup_official_pdf(
            source_path=previous_output_path,
            backup_path=get_chunk_doc_backup_pdf_path(job_id, lesson_name, previous_chunk_name),
        )

        metrics = _write_previous_and_selected_official_pdfs(
            source_pdf=lesson_pdf_path,
            previous_output_pdf=previous_output_path,
            selected_output_pdf=selected_output_path,
            previous_start=previous_start,
            selected_start=selected_start,
            selected_end=selected_end,
            y_cut_image=float(y_cut),
            image_height=float(image_height),
        )

    debug_promote_json_path = get_chunk_cutline_promote_json_path(
        job_id,
        lesson_name,
        chunk_name,
    )
    debug_payload = {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "selected_chunk": chunk_name,
        "previous_chunk": previous_chunk_name,
        "source_lesson_pdf": str(lesson_pdf_path),
        "page_number": page_number,
        "y_cut_image": y_cut,
        "image_height": image_height,
        "pdf_page_height": metrics["pdf_page_height"],
        "y_cut_pdf": metrics["y_cut_pdf"],
        "match_score": cutline.get("match_score"),
        "matched_prefix": cutline.get("matched_prefix"),
        "expected_len": cutline.get("expected_len"),
        "match_ratio": cutline.get("match_ratio"),
        "best_mode": cutline.get("best_mode"),
        "weak_cut": cutline.get("weak_cut"),
        "force_cut": cutline.get("force_cut"),
        "early_stop": cutline.get("early_stop"),
        "official_outputs": {
            "previous_chunk_pdf": str(previous_output_path) if previous_output_path else None,
            "selected_chunk_pdf": str(selected_output_path),
        },
        "backups": {
            "previous_chunk_backup": str(previous_backup_path) if previous_backup_path else None,
            "selected_chunk_backup": str(selected_backup_path) if selected_backup_path else None,
        },
        "promoted": True,
    }
    write_json(debug_promote_json_path, debug_payload)

    return ChunkCutlinePromoteResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        selected_chunk=chunk_name,
        previous_chunk=previous_chunk_name,
        promoted=True,
        selected_chunk_pdf=str(selected_output_path),
        previous_chunk_pdf=str(previous_output_path) if previous_output_path else None,
        debug_promote_json_path=str(debug_promote_json_path),
    )


def _write_previous_and_selected_official_pdfs(
    *,
    source_pdf: Path,
    previous_output_pdf: Path,
    selected_output_pdf: Path,
    previous_start: int,
    selected_start: int,
    selected_end: int,
    y_cut_image: float,
    image_height: float,
) -> dict[str, float]:
    import fitz

    if image_height <= 0:
        raise ChunkCutlinePromoteInputError("image_height must be greater than 0.")

    source_doc = fitz.open(str(source_pdf))
    try:
        page_rect, y_cut_pdf = _get_cutline_metrics(
            source_doc=source_doc,
            selected_start=selected_start,
            selected_end=selected_end,
            y_cut_image=y_cut_image,
            image_height=image_height,
            extra_pages=[previous_start],
        )

        previous_doc = fitz.open()
        if previous_start <= selected_start - 1:
            previous_doc.insert_pdf(
                source_doc,
                from_page=previous_start - 1,
                to_page=selected_start - 2,
            )
        _append_cropped_page(
            output_doc=previous_doc,
            source_doc=source_doc,
            page_index=selected_start - 1,
            crop_rect=fitz.Rect(page_rect.x0, page_rect.y0, page_rect.x1, y_cut_pdf),
        )
        _atomic_save_pdf(previous_doc, previous_output_pdf)

        selected_doc = _build_selected_doc(
            source_doc=source_doc,
            selected_start=selected_start,
            selected_end=selected_end,
            page_rect=page_rect,
            y_cut_pdf=y_cut_pdf,
        )
        _atomic_save_pdf(selected_doc, selected_output_pdf)

        return {
            "pdf_page_height": float(page_rect.height),
            "y_cut_pdf": float(y_cut_pdf),
        }
    finally:
        source_doc.close()


def _write_selected_official_pdf(
    *,
    source_pdf: Path,
    selected_output_pdf: Path,
    selected_start: int,
    selected_end: int,
    y_cut_image: float,
    image_height: float,
) -> dict[str, float]:
    import fitz

    if image_height <= 0:
        raise ChunkCutlinePromoteInputError("image_height must be greater than 0.")

    source_doc = fitz.open(str(source_pdf))
    try:
        page_rect, y_cut_pdf = _get_cutline_metrics(
            source_doc=source_doc,
            selected_start=selected_start,
            selected_end=selected_end,
            y_cut_image=y_cut_image,
            image_height=image_height,
        )
        selected_doc = _build_selected_doc(
            source_doc=source_doc,
            selected_start=selected_start,
            selected_end=selected_end,
            page_rect=page_rect,
            y_cut_pdf=y_cut_pdf,
        )
        _atomic_save_pdf(selected_doc, selected_output_pdf)

        return {
            "pdf_page_height": float(page_rect.height),
            "y_cut_pdf": float(y_cut_pdf),
        }
    finally:
        source_doc.close()


def _build_selected_doc(
    *,
    source_doc: Any,
    selected_start: int,
    selected_end: int,
    page_rect: Any,
    y_cut_pdf: float,
) -> Any:
    import fitz

    selected_doc = fitz.open()
    _append_cropped_page(
        output_doc=selected_doc,
        source_doc=source_doc,
        page_index=selected_start - 1,
        crop_rect=fitz.Rect(page_rect.x0, y_cut_pdf, page_rect.x1, page_rect.y1),
    )
    if selected_start + 1 <= selected_end:
        selected_doc.insert_pdf(
            source_doc,
            from_page=selected_start,
            to_page=selected_end - 1,
        )
    return selected_doc


def _get_cutline_metrics(
    *,
    source_doc: Any,
    selected_start: int,
    selected_end: int,
    y_cut_image: float,
    image_height: float,
    extra_pages: list[int] | None = None,
) -> tuple[Any, float]:
    total_pages = source_doc.page_count
    pages_to_check = [selected_start, selected_end]
    if extra_pages:
        pages_to_check.extend(extra_pages)

    for page_number in pages_to_check:
        if page_number < 1 or page_number > total_pages:
            raise ChunkCutlinePromoteInputError(
                f"Page {page_number} is outside lesson PDF page count {total_pages}."
            )
    if selected_end < selected_start:
        raise ChunkCutlinePromoteInputError("Selected chunk end page must be greater than or equal to start page.")

    source_page = source_doc[selected_start - 1]
    page_rect = source_page.rect
    y_cut_pdf = convert_y_cut_image_to_pdf(
        y_cut_image=y_cut_image,
        image_height=image_height,
        pdf_page_height=float(page_rect.height),
    )
    return page_rect, y_cut_pdf


def convert_y_cut_image_to_pdf(
    *,
    y_cut_image: float,
    image_height: float,
    pdf_page_height: float,
) -> float:
    if image_height <= 0:
        raise ChunkCutlinePromoteInputError("image_height must be greater than 0.")
    if pdf_page_height <= 0:
        raise ChunkCutlinePromoteInputError("pdf_page_height must be greater than 0.")

    y_cut_pdf = y_cut_image * pdf_page_height / image_height
    return max(0.0, min(float(y_cut_pdf), float(pdf_page_height)))


def _append_cropped_page(
    *,
    output_doc: Any,
    source_doc: Any,
    page_index: int,
    crop_rect: Any,
) -> None:
    if crop_rect.height <= 0 or crop_rect.width <= 0:
        raise ChunkCutlinePromoteInputError("Cutline crop produced an empty page region.")

    page = source_doc[page_index]
    original_crop = page.cropbox
    try:
        page.set_cropbox(crop_rect)
        output_doc.insert_pdf(source_doc, from_page=page_index, to_page=page_index)
    finally:
        page.set_cropbox(original_crop)


def _atomic_save_pdf(doc: Any, output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    temp_pdf = output_pdf.with_name(f".{output_pdf.stem}.tmp{output_pdf.suffix}")
    if temp_pdf.exists():
        temp_pdf.unlink()

    try:
        doc.save(str(temp_pdf), garbage=4, deflate=True)
        temp_pdf.replace(output_pdf)
    finally:
        doc.close()
        if temp_pdf.exists():
            temp_pdf.unlink()


def _backup_official_pdf(*, source_path: Path, backup_path: Path) -> Path | None:
    if not source_path.exists():
        return None

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if not backup_path.exists():
        shutil.copyfile(source_path, backup_path)
    return backup_path


def _validate_cutline_confidence(cutline: dict[str, Any]) -> None:
    if bool(cutline.get("force_cut")) or bool(cutline.get("weak_cut")):
        return

    matched_prefix = _optional_int(cutline.get("matched_prefix"))
    if matched_prefix is not None and matched_prefix >= MIN_MATCH_REQUIRED:
        return

    match_ratio = _optional_float(cutline.get("match_ratio"))
    if match_ratio is not None and match_ratio >= 0.5:
        return

    raise ChunkCutlinePromoteInputError("Cutline confidence is too low to promote safely.")


def _get_image_height(*, cutline: dict[str, Any], page_image_path: Path) -> int:
    for key in ["image_height", "page_image_height"]:
        value = _optional_int(cutline.get(key))
        if value is not None and value > 0:
            return value

    image_size = cutline.get("image_size")
    if isinstance(image_size, dict):
        value = _optional_int(image_size.get("h") or image_size.get("height"))
        if value is not None and value > 0:
            return value

    if not page_image_path.exists():
        raise FileNotFoundError(f"Cutline page image was not found: {page_image_path}")

    from PIL import Image

    with Image.open(page_image_path) as image:
        return int(image.height)


def _is_first_chunk(*, chunk_name: str, selected_chunk: dict[str, Any]) -> bool:
    return chunk_name == "chunk_01" or bool(selected_chunk.get("first_chunk"))


def _previous_chunk_name(chunk_name: str) -> str:
    match = __import__("re").match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        raise ChunkCutlinePromoteInputError(
            f"Chunk name must use format chunk_XX: {chunk_name}"
        )

    number_text = match.group(1)
    number = int(number_text)
    if number <= 1:
        raise ChunkCutlinePromoteInputError("chunk_01 has no previous chunk.")

    return f"chunk_{number - 1:0{len(number_text)}d}"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ChunkCutlinePromoteInputError(f"{label} JSON must contain an object: {path}")
    return payload


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    parsed = _optional_int(value)
    if parsed is None:
        raise ChunkCutlinePromoteInputError(f"Required integer field is missing: {field}")
    return parsed


def _required_number(payload: dict[str, Any], field: str) -> float:
    value = _optional_float(payload.get(field))
    if value is None:
        raise ChunkCutlinePromoteInputError(f"Required numeric field is missing: {field}")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ChunkCutlinePromoteInputError",
    "convert_y_cut_image_to_pdf",
    "promote_cutline_for_chunk",
]
