from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.extraction import ChunkCutlineApplyResponse
from app.services.extraction.job_service import get_job
from app.services.storage.workspace_service import (
    get_chunk_cutline_apply_json_path,
    get_chunk_cutline_json_path,
    get_chunk_cutline_page_image_path,
    get_chunk_cutline_pdf_path,
    get_chunk_json_path,
    get_lesson_doc_path,
    read_json,
    write_json,
)


MIN_MATCH_REQUIRED = 3


class ChunkCutlineApplyInputError(ValueError):
    pass


def apply_cutline_for_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> ChunkCutlineApplyResponse:
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

    if chunk_name == "chunk_01":
        raise ChunkCutlineApplyInputError("chunk_01 has no previous chunk to recut.")

    if not bool(selected_chunk.get("content_head")):
        raise ChunkCutlineApplyInputError("Selected chunk must have content_head=true.")

    if not bool(cutline.get("matched")):
        raise ChunkCutlineApplyInputError("Cutline result must have matched=true.")

    y_cut = _required_number(cutline, "y_cut")
    selected_start = _required_int(selected_chunk, "start")
    selected_end = _required_int(selected_chunk, "end")
    page_number = _required_int(cutline, "page_number")

    if page_number != selected_start:
        raise ChunkCutlineApplyInputError(
            f"Cutline page_number={page_number} does not match selected chunk start={selected_start}."
        )

    _validate_cutline_confidence(cutline)

    previous_chunk_name = _previous_chunk_name(chunk_name)
    previous_chunk_path = get_chunk_json_path(job_id, lesson_name, previous_chunk_name)
    if not previous_chunk_path.exists():
        raise FileNotFoundError(f"Previous chunk JSON was not found: {previous_chunk_path}")

    previous_chunk = _read_object(previous_chunk_path, "previous chunk")
    previous_start = _required_int(previous_chunk, "start")

    image_height = _get_image_height(
        cutline=cutline,
        page_image_path=get_chunk_cutline_page_image_path(job_id, lesson_name, chunk_name),
    )

    previous_output_path = get_chunk_cutline_pdf_path(
        job_id,
        lesson_name,
        previous_chunk_name,
    )
    selected_output_path = get_chunk_cutline_pdf_path(
        job_id,
        lesson_name,
        chunk_name,
    )

    metrics = _write_recut_pdfs(
        source_pdf=lesson_pdf_path,
        previous_output_pdf=previous_output_path,
        selected_output_pdf=selected_output_path,
        previous_start=previous_start,
        selected_start=selected_start,
        selected_end=selected_end,
        y_cut_image=float(y_cut),
        image_height=float(image_height),
    )

    debug_apply_json_path = get_chunk_cutline_apply_json_path(
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
        "outputs": {
            "previous_chunk_pdf": str(previous_output_path),
            "selected_chunk_pdf": str(selected_output_path),
        },
        "applied": True,
    }
    write_json(debug_apply_json_path, debug_payload)

    return ChunkCutlineApplyResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        selected_chunk=chunk_name,
        previous_chunk=previous_chunk_name,
        applied=True,
        previous_chunk_pdf=str(previous_output_path),
        selected_chunk_pdf=str(selected_output_path),
        debug_apply_json_path=str(debug_apply_json_path),
    )


def _write_recut_pdfs(
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
        raise ChunkCutlineApplyInputError("image_height must be greater than 0.")

    source_doc = fitz.open(str(source_pdf))
    try:
        total_pages = source_doc.page_count
        for page_number in [previous_start, selected_start, selected_end]:
            if page_number < 1 or page_number > total_pages:
                raise ChunkCutlineApplyInputError(
                    f"Page {page_number} is outside lesson PDF page count {total_pages}."
                )

        source_page = source_doc[selected_start - 1]
        page_rect = source_page.rect
        y_cut_pdf = y_cut_image * float(page_rect.height) / image_height
        y_cut_pdf = max(0.0, min(float(y_cut_pdf), float(page_rect.height)))

        previous_output_pdf.parent.mkdir(parents=True, exist_ok=True)
        selected_output_pdf.parent.mkdir(parents=True, exist_ok=True)

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
        previous_doc.save(str(previous_output_pdf), garbage=4, deflate=True)
        previous_doc.close()

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
        selected_doc.save(str(selected_output_pdf), garbage=4, deflate=True)
        selected_doc.close()

        return {
            "pdf_page_height": float(page_rect.height),
            "y_cut_pdf": float(y_cut_pdf),
        }
    finally:
        source_doc.close()


def _append_cropped_page(
    *,
    output_doc: Any,
    source_doc: Any,
    page_index: int,
    crop_rect: Any,
) -> None:
    if crop_rect.height <= 0 or crop_rect.width <= 0:
        raise ChunkCutlineApplyInputError("Cutline crop produced an empty page region.")

    page = source_doc[page_index]
    original_crop = page.cropbox
    try:
        page.set_cropbox(crop_rect)
        output_doc.insert_pdf(source_doc, from_page=page_index, to_page=page_index)
    finally:
        page.set_cropbox(original_crop)


def _validate_cutline_confidence(cutline: dict[str, Any]) -> None:
    if bool(cutline.get("force_cut")) or bool(cutline.get("weak_cut")):
        return

    matched_prefix = _optional_int(cutline.get("matched_prefix"))
    if matched_prefix is not None and matched_prefix >= MIN_MATCH_REQUIRED:
        return

    match_ratio = _optional_float(cutline.get("match_ratio"))
    if match_ratio is not None and match_ratio >= 0.5:
        return

    raise ChunkCutlineApplyInputError("Cutline confidence is too low to apply safely.")


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


def _previous_chunk_name(chunk_name: str) -> str:
    match = __import__("re").match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        raise ChunkCutlineApplyInputError(
            f"Chunk name must use format chunk_XX: {chunk_name}"
        )

    number_text = match.group(1)
    number = int(number_text)
    if number <= 1:
        raise ChunkCutlineApplyInputError("chunk_01 has no previous chunk to recut.")

    return f"chunk_{number - 1:0{len(number_text)}d}"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ChunkCutlineApplyInputError(f"{label} JSON must contain an object: {path}")
    return payload


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    parsed = _optional_int(value)
    if parsed is None:
        raise ChunkCutlineApplyInputError(f"Required integer field is missing: {field}")
    return parsed


def _required_number(payload: dict[str, Any], field: str) -> float:
    value = _optional_float(payload.get(field))
    if value is None:
        raise ChunkCutlineApplyInputError(f"Required numeric field is missing: {field}")
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
