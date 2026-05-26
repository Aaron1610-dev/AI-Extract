from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.services.extraction.chunk_cutline_promote_service import (
    InternalPromoteInputError,
    promote_cutline_for_chunk,
)
from app.services.extraction.job_service import get_job
from app.services.kaggle_cutline_debug_service import (
    KaggleCutlineNotConfigured,
    run_kaggle_cutline_debug,
)
from app.services.storage.workspace_service import (
    get_chunk_cutline_bbox_image_path,
    get_chunk_cutline_json_path,
    get_chunk_cutline_page_image_path,
    get_chunk_cutline_request_dir,
    get_chunk_json_path,
    get_lesson_doc_path,
    read_json,
    write_json,
)


DPI = 260


class ChunkCutlineInputError(ValueError):
    pass


@dataclass(frozen=True)
class CutlineDetectionResult:
    job_id: str
    lesson_name: str
    chunk_name: str
    matched: bool
    page_number: int
    heading: str
    title: str
    matched_text: str | None
    bbox: list[int] | None
    y_cut: int | None
    match_score: int | None
    matched_prefix: int | None
    expected_len: int | None
    match_ratio: float | None
    best_mode: str | None
    weak_cut: bool | None
    force_cut: bool | None
    early_stop: bool | None
    reason: str | None
    debug_json_path: str
    debug_page_path: str
    debug_bbox_path: str | None
    artifact: dict[str, Any]


def detect_debug_cutline_for_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> dict[str, Any]:
    detection = detect_cutline_artifacts_for_chunk(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_name=chunk_name,
    )
    chunk_json_path = get_chunk_json_path(job_id, lesson_name, chunk_name)
    chunk = read_json(chunk_json_path)
    if not isinstance(chunk, dict):
        raise ChunkCutlineInputError(f"Chunk JSON must contain an object: {chunk_json_path}")

    promote_status = "not_run"
    promote_reason = None
    promote_response = None
    if detection.matched:
        if not _is_first_chunk(chunk_name=chunk_name, selected_chunk=chunk) and not bool(
            chunk.get("content_head")
        ):
            promote_status = "skipped"
            promote_reason = (
                "Selected chunk does not have content_head=true; page-range doc is already sufficient."
            )
        else:
            try:
                promote_response = promote_cutline_for_chunk(
                    job_id=job_id,
                    lesson_name=lesson_name,
                    chunk_name=chunk_name,
                )
                promote_status = "promoted"
            except InternalPromoteInputError as exc:
                promote_status = "skipped"
                promote_reason = str(exc)

    return {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "chunk_name": chunk_name,
        "matched": detection.matched,
        "page_number": detection.page_number,
        "heading": detection.heading,
        "title": detection.title,
        "matched_text": detection.matched_text,
        "bbox": detection.bbox,
        "y_cut": detection.y_cut,
        "match_score": detection.match_score,
        "matched_prefix": detection.matched_prefix,
        "expected_len": detection.expected_len,
        "match_ratio": detection.match_ratio,
        "best_mode": detection.best_mode,
        "weak_cut": detection.weak_cut,
        "force_cut": detection.force_cut,
        "early_stop": detection.early_stop,
        "reason": detection.reason,
        "debug_json_path": detection.debug_json_path,
        "debug_page_path": detection.debug_page_path,
        "debug_bbox_path": detection.debug_bbox_path,
        "promoted": bool(promote_response and promote_response.promoted),
        "promote_status": promote_status,
        "promote_reason": promote_reason,
        "previous_chunk": promote_response.previous_chunk if promote_response else None,
        "selected_chunk_pdf": promote_response.selected_chunk_pdf if promote_response else None,
        "previous_chunk_pdf": promote_response.previous_chunk_pdf if promote_response else None,
        "debug_promote_json_path": (
            promote_response.debug_promote_json_path if promote_response else None
        ),
    }


def detect_cutline_artifacts_for_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> CutlineDetectionResult:
    get_job(job_id)

    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    chunk_json_path = get_chunk_json_path(job_id, lesson_name, chunk_name)
    if not chunk_json_path.exists():
        raise FileNotFoundError(f"Chunk JSON was not found: {chunk_json_path}")

    chunk = read_json(chunk_json_path)
    if not isinstance(chunk, dict):
        raise ChunkCutlineInputError(f"Chunk JSON must contain an object: {chunk_json_path}")

    page_number = _required_int(chunk, "start")
    heading = _required_str(chunk, "heading")
    title = _required_str(chunk, "title")

    request_id = str(uuid4())
    request_payload = {
        "request_id": request_id,
        "job_id": job_id,
        "lesson_name": lesson_name,
        "chunk_name": chunk_name,
        "page_number": page_number,
        "heading": heading,
        "title": title,
    }

    page_image_path = get_chunk_cutline_page_image_path(job_id, lesson_name, chunk_name)
    bbox_image_path = get_chunk_cutline_bbox_image_path(job_id, lesson_name, chunk_name)
    debug_json_path = get_chunk_cutline_json_path(job_id, lesson_name, chunk_name)
    request_dir = get_chunk_cutline_request_dir(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_name=chunk_name,
    )

    _render_pdf_page_to_png(
        pdf_path=lesson_pdf_path,
        page_number=page_number,
        output_png=page_image_path,
        dpi=DPI,
    )

    result = run_kaggle_cutline_debug(
        request_payload=request_payload,
        page_image_path=page_image_path,
        request_dir=request_dir,
    )
    _copy_kaggle_bbox_image(
        kaggle_output_dir=_optional_str(result.get("_kaggle_output_dir")),
        request_id=request_id,
        target_path=bbox_image_path,
    )

    artifact = {
        **request_payload,
        **{key: value for key, value in result.items() if not key.startswith("_")},
        "debug_page_path": str(page_image_path),
        "debug_bbox_path": str(bbox_image_path) if bbox_image_path.exists() else None,
    }
    write_json(debug_json_path, artifact)

    return CutlineDetectionResult(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_name=chunk_name,
        matched=bool(result.get("matched", False)),
        page_number=page_number,
        heading=heading,
        title=title,
        matched_text=_optional_str(result.get("matched_text")),
        bbox=_int_list_or_none(result.get("bbox")),
        y_cut=_optional_int(result.get("y_cut")),
        match_score=_optional_int(result.get("match_score") or result.get("best_match_score")),
        matched_prefix=_optional_int(result.get("matched_prefix")),
        expected_len=_optional_int(result.get("expected_len")),
        match_ratio=_optional_float(result.get("match_ratio")),
        best_mode=_optional_str(result.get("best_mode")),
        weak_cut=_optional_bool(result.get("weak_cut")),
        force_cut=_optional_bool(result.get("force_cut")),
        early_stop=_optional_bool(result.get("early_stop")),
        reason=_optional_str(result.get("reason")),
        debug_json_path=str(debug_json_path),
        debug_page_path=str(page_image_path),
        debug_bbox_path=str(bbox_image_path) if bbox_image_path.exists() else None,
        artifact=artifact,
    )


def _render_pdf_page_to_png(
    *,
    pdf_path: Path,
    page_number: int,
    output_png: Path,
    dpi: int,
) -> Path:
    import fitz

    if page_number < 1:
        raise ChunkCutlineInputError("Chunk start page must be a 1-based page number.")

    doc = fitz.open(str(pdf_path))
    try:
        if page_number > doc.page_count:
            raise ChunkCutlineInputError(
                f"Chunk start page {page_number} is outside lesson PDF page count {doc.page_count}."
            )

        page = doc.load_page(page_number - 1)
        zoom = float(dpi) / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        output_png.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(output_png))
        return output_png
    finally:
        doc.close()


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise ChunkCutlineInputError(f"Chunk JSON must include integer field '{field}'.")

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ChunkCutlineInputError(
            f"Chunk JSON field '{field}' must be an integer."
        ) from exc


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ChunkCutlineInputError(f"Chunk JSON must include non-empty field '{field}'.")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _int_list_or_none(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None

    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        return None


def _copy_kaggle_bbox_image(
    *,
    kaggle_output_dir: str | None,
    request_id: str,
    target_path: Path,
) -> None:
    if not kaggle_output_dir:
        return

    output_dir = Path(kaggle_output_dir)
    possible_names = [
        "bbox.png",
        "cutline_bbox.png",
        f"{request_id}_bbox.png",
        f"{request_id}_cutline.png",
    ]

    for name in possible_names:
        source_path = output_dir / name
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            return


def _is_first_chunk(*, chunk_name: str, selected_chunk: dict[str, Any]) -> bool:
    return chunk_name == "chunk_01" or bool(selected_chunk.get("first_chunk"))


__all__ = [
    "ChunkCutlineInputError",
    "CutlineDetectionResult",
    "KaggleCutlineNotConfigured",
    "detect_cutline_artifacts_for_chunk",
    "detect_debug_cutline_for_chunk",
]
