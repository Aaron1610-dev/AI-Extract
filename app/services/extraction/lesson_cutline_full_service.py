from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.schemas.extraction import LessonCutlineFullResponse
from app.services.extraction.chunk_cutline_debug_service import (
    ChunkCutlineInputError,
    DPI,
)
from app.services.extraction.chunk_debug_service import NO_MAIN_CHUNK_TITLE
from app.services.extraction.chunk_cutline_promote_service import (
    InternalPromoteInputError,
    convert_y_cut_image_to_pdf,
    get_cutline_image_height,
    validate_cutline_confidence,
)
from app.services.extraction.job_service import get_job
from app.services.extraction.keyword_debug_service import extract_keywords_for_lesson_debug
from app.services.kaggle_cutline_debug_service import run_kaggle_cutline_batch
from app.services.storage.workspace_service import (
    get_chunk_cutline_bbox_image_path,
    get_chunk_cutline_json_path,
    get_chunk_cutline_page_image_path,
    get_chunk_doc_dir,
    get_chunk_lesson_debug_dir,
    get_chunk_lesson_dir,
    get_chunk_pdf_path,
    get_chunks_approved_json_path,
    get_lesson_cutline_full_json_path,
    get_lesson_doc_path,
    read_json,
    write_json,
)


class LessonCutlineFullInputError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkRecord:
    name: str
    start: int
    end: int
    path: Path
    payload: dict[str, Any]


@dataclass(frozen=True)
class CutlineBoundary:
    chunk_name: str
    page_number: int
    y_cut_image: int
    image_height: int
    y_cut_pdf: float
    match_score: int | None
    best_mode: str | None


def process_full_lesson_cutlines(
    job_id: str,
    lesson_name: str,
) -> LessonCutlineFullResponse:
    get_job(job_id)

    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    approved_path = get_chunks_approved_json_path(job_id, lesson_name)
    if not approved_path.exists():
        raise LessonCutlineFullInputError(
            "Chunks must be approved before finalize. Run /chunks/lesson/{lesson_name}/approve first."
        )

    chunks = _load_lesson_chunks(job_id=job_id, lesson_name=lesson_name)
    if not chunks:
        raise LessonCutlineFullInputError(f"No chunk JSON files were found for lesson: {lesson_name}")

    processed_chunks: list[str] = []
    skipped_chunks: list[dict[str, str]] = []
    failed_chunks: list[dict[str, str]] = []
    boundaries: dict[str, CutlineBoundary] = {}
    required_chunks: list[ChunkRecord] = []

    for chunk in chunks:
        if not _needs_cutline_detection(chunk):
            skipped_chunks.append(
                {
                    "chunk_name": chunk.name,
                    "reason": _skip_reason(chunk),
                }
            )
            continue
        required_chunks.append(chunk)

    request_id: str | None = None
    if required_chunks:
        request_id = str(uuid4())
        page_image_paths: dict[str, Path] = {}
        request_items: list[dict[str, Any]] = []
        for chunk in required_chunks:
            page_image_path = get_chunk_cutline_page_image_path(
                job_id,
                lesson_name,
                chunk.name,
            )
            _render_pdf_page_to_png(
                pdf_path=lesson_pdf_path,
                page_number=chunk.start,
                output_png=page_image_path,
                dpi=DPI,
            )
            page_image_paths[chunk.name] = page_image_path
            request_items.append(
                {
                    "chunk_name": chunk.name,
                    "page_number": chunk.start,
                    "image_file": f"pages/{chunk.name}.png",
                    "heading": _required_str(chunk.payload, "heading"),
                    "title": _required_str(chunk.payload, "title"),
                }
            )

        request_payload = {
            "request_id": request_id,
            "job_id": job_id,
            "lesson_name": lesson_name,
            "mode": "lesson_cutline_full",
            "items": request_items,
        }
        batch_result = run_kaggle_cutline_batch(
            request_payload=request_payload,
            page_image_paths=page_image_paths,
            request_dir=get_chunk_lesson_debug_dir(job_id, lesson_name) / "kaggle_batch",
        )
        result_by_chunk = _index_batch_results(batch_result)
        kaggle_output_dir = _optional_str(batch_result.get("_kaggle_output_dir"))

        for chunk in required_chunks:
            request_item = next(
                item for item in request_items if item["chunk_name"] == chunk.name
            )
            cutline = result_by_chunk.get(chunk.name)
            if cutline is None:
                failed_chunks.append(
                    {
                        "chunk_name": chunk.name,
                        "reason": "Kaggle batch output did not include this chunk.",
                    }
                )
                continue

            artifact = _save_batch_cutline_artifacts(
                job_id=job_id,
                lesson_name=lesson_name,
                request_id=request_id,
                request_item=request_item,
                cutline=cutline,
                kaggle_output_dir=kaggle_output_dir,
            )
            if not bool(artifact.get("matched")):
                failed_chunks.append(
                    {
                        "chunk_name": chunk.name,
                        "reason": _optional_str(artifact.get("reason"))
                        or "Cutline detection did not match.",
                    }
                )
                continue

            try:
                validate_cutline_confidence(artifact)
                y_cut_image = _required_int(artifact, "y_cut")
                image_height = get_cutline_image_height(
                    cutline=artifact,
                    page_image_path=get_chunk_cutline_page_image_path(
                        job_id,
                        lesson_name,
                        chunk.name,
                    ),
                )
                pdf_page_height = _get_pdf_page_height(
                    source_pdf=lesson_pdf_path,
                    page_number=chunk.start,
                )
                y_cut_pdf = convert_y_cut_image_to_pdf(
                    y_cut_image=float(y_cut_image),
                    image_height=float(image_height),
                    pdf_page_height=pdf_page_height,
                )
                boundaries[chunk.name] = CutlineBoundary(
                    chunk_name=chunk.name,
                    page_number=chunk.start,
                    y_cut_image=y_cut_image,
                    image_height=image_height,
                    y_cut_pdf=y_cut_pdf,
                    match_score=_optional_int(
                        artifact.get("match_score") or artifact.get("best_match_score")
                    ),
                    best_mode=_optional_str(artifact.get("best_mode")),
                )
                processed_chunks.append(chunk.name)

            except (
                ChunkCutlineInputError,
                InternalPromoteInputError,
                LessonCutlineFullInputError,
                FileNotFoundError,
            ) as exc:
                failed_chunks.append({"chunk_name": chunk.name, "reason": str(exc)})

    summary_path = get_lesson_cutline_full_json_path(job_id, lesson_name)
    if failed_chunks:
        summary_payload = _build_summary_payload(
            job_id=job_id,
            lesson_name=lesson_name,
            lesson_pdf_path=lesson_pdf_path,
            processed_chunks=processed_chunks,
            skipped_chunks=skipped_chunks,
            failed_chunks=failed_chunks,
            updated_pdfs=[],
            boundaries=boundaries,
            status="failed",
            kaggle_request_id=request_id,
            kaggle_runs=1 if required_chunks else 0,
        )
        write_json(summary_path, summary_payload)
        return _response_from_summary(summary_payload, summary_path)

    updated_pdf_paths = _rebuild_lesson_chunk_pdfs(
        source_pdf=lesson_pdf_path,
        job_id=job_id,
        lesson_name=lesson_name,
        chunks=chunks,
        boundaries=boundaries,
    )
    updated_pdfs = [path.name for path in updated_pdf_paths]
    summary_payload = _build_summary_payload(
        job_id=job_id,
        lesson_name=lesson_name,
        lesson_pdf_path=lesson_pdf_path,
        processed_chunks=processed_chunks,
        skipped_chunks=skipped_chunks,
        failed_chunks=[],
        updated_pdfs=updated_pdfs,
        boundaries=boundaries,
        status="completed",
        kaggle_request_id=request_id,
        kaggle_runs=1 if required_chunks else 0,
    )
    try:
        keyword_response = extract_keywords_for_lesson_debug(
            job_id=job_id,
            lesson_name=lesson_name,
        )
        keyword_results = [item.model_dump(mode="json") for item in keyword_response.results]
        summary_payload["keyword_extracted"] = True
        summary_payload["keyword_paths"] = [
            item["keyword_path"]
            for item in keyword_results
            if isinstance(item.get("keyword_path"), str)
        ]
        summary_payload["keyword_results"] = keyword_results

    except Exception as exc:
        summary_payload["status"] = "completed_with_keyword_error"
        summary_payload["keyword_extracted"] = False
        summary_payload["keyword_error"] = f"Gemini keyword extraction failed: {exc}"

    write_json(summary_path, summary_payload)
    return _response_from_summary(summary_payload, summary_path)


def _load_lesson_chunks(*, job_id: str, lesson_name: str) -> list[ChunkRecord]:
    lesson_chunk_dir = get_chunk_lesson_dir(job_id, lesson_name)
    if not lesson_chunk_dir.exists():
        raise FileNotFoundError(f"Chunk lesson directory was not found: {lesson_chunk_dir}")

    chunks: list[ChunkRecord] = []
    for path in sorted(lesson_chunk_dir.glob("chunk_*.json"), key=lambda item: _chunk_sort_key(item.stem)):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise LessonCutlineFullInputError(f"Chunk JSON must contain an object: {path}")
        chunks.append(
            ChunkRecord(
                name=path.stem,
                start=_required_int(payload, "start"),
                end=_required_int(payload, "end"),
                path=path,
                payload=payload,
            )
        )
    return chunks


def _needs_cutline_detection(chunk: ChunkRecord) -> bool:
    if _is_no_heading_chunk(chunk):
        return False
    if not _optional_str(chunk.payload.get("heading")):
        return False
    if chunk.name == "chunk_01":
        return bool(chunk.payload.get("first_chunk"))
    return bool(chunk.payload.get("content_head"))


def _skip_reason(chunk: ChunkRecord) -> str:
    if _is_no_heading_chunk(chunk) or not _optional_str(chunk.payload.get("heading")):
        return "heading=null; no cutline needed"
    if chunk.name == "chunk_01":
        return "first_chunk=false"
    return "content_head=false"


def _is_no_heading_chunk(chunk: ChunkRecord) -> bool:
    return (
        chunk.name == "chunk_01"
        and chunk.payload.get("heading") is None
        and chunk.payload.get("title") == NO_MAIN_CHUNK_TITLE
    )


def _index_batch_results(batch_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = batch_result.get("results")
    if not isinstance(results, list):
        raise LessonCutlineFullInputError("Kaggle batch output must include results list.")

    indexed: dict[str, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        chunk_name = _optional_str(item.get("chunk_name"))
        if chunk_name:
            indexed[chunk_name] = item
    return indexed


def _save_batch_cutline_artifacts(
    *,
    job_id: str,
    lesson_name: str,
    request_id: str,
    request_item: dict[str, Any],
    cutline: dict[str, Any],
    kaggle_output_dir: str | None,
) -> dict[str, Any]:
    chunk_name = str(request_item["chunk_name"])
    page_image_path = get_chunk_cutline_page_image_path(job_id, lesson_name, chunk_name)
    bbox_image_path = get_chunk_cutline_bbox_image_path(job_id, lesson_name, chunk_name)
    debug_json_path = get_chunk_cutline_json_path(job_id, lesson_name, chunk_name)
    _copy_batch_bbox_image(
        kaggle_output_dir=kaggle_output_dir,
        chunk_name=chunk_name,
        target_path=bbox_image_path,
    )

    artifact = {
        "request_id": request_id,
        "job_id": job_id,
        "lesson_name": lesson_name,
        **request_item,
        **{key: value for key, value in cutline.items() if not key.startswith("_")},
        "debug_page_path": str(page_image_path),
        "debug_bbox_path": str(bbox_image_path) if bbox_image_path.exists() else None,
    }
    write_json(debug_json_path, artifact)
    return artifact


def _copy_batch_bbox_image(
    *,
    kaggle_output_dir: str | None,
    chunk_name: str,
    target_path: Path,
) -> None:
    if not kaggle_output_dir:
        return

    source_path = Path(kaggle_output_dir) / "bbox" / f"{chunk_name}.png"
    if not source_path.exists():
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)


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


def _rebuild_lesson_chunk_pdfs(
    *,
    source_pdf: Path,
    job_id: str,
    lesson_name: str,
    chunks: list[ChunkRecord],
    boundaries: dict[str, CutlineBoundary],
) -> list[Path]:
    import fitz

    get_chunk_doc_dir(job_id, lesson_name).mkdir(parents=True, exist_ok=True)
    source_doc = fitz.open(str(source_pdf))
    updated_paths: list[Path] = []
    try:
        for index, chunk in enumerate(chunks):
            _validate_page_range(source_doc=source_doc, chunk=chunk)
            next_chunk = chunks[index + 1] if index + 1 < len(chunks) else None
            start_boundary = boundaries.get(chunk.name)
            end_boundary = (
                boundaries.get(next_chunk.name)
                if next_chunk is not None
                and next_chunk.start >= chunk.start
                and next_chunk.start <= chunk.end
                else None
            )
            output_pdf = get_chunk_pdf_path(job_id, lesson_name, chunk.name)
            output_doc = _build_chunk_doc(
                source_doc=source_doc,
                chunk=chunk,
                start_boundary=start_boundary,
                end_boundary=end_boundary,
            )
            _atomic_save_pdf(output_doc, output_pdf)
            updated_paths.append(output_pdf)
    finally:
        source_doc.close()
    return updated_paths


def _build_chunk_doc(
    *,
    source_doc: Any,
    chunk: ChunkRecord,
    start_boundary: CutlineBoundary | None,
    end_boundary: CutlineBoundary | None,
) -> Any:
    import fitz

    output_doc = fitz.open()
    start_page = chunk.start
    start_y = 0.0
    if start_boundary is not None:
        start_page = start_boundary.page_number
        start_y = start_boundary.y_cut_pdf

    end_page = chunk.end
    end_y: float | None = None
    if end_boundary is not None:
        end_page = end_boundary.page_number
        end_y = end_boundary.y_cut_pdf

    if end_page < start_page:
        raise LessonCutlineFullInputError(
            f"Cutline boundaries produce an invalid range for {chunk.name}."
        )

    if start_page == end_page:
        page_rect = source_doc[start_page - 1].rect
        _append_cropped_page(
            output_doc=output_doc,
            source_doc=source_doc,
            page_number=start_page,
            crop_rect=fitz.Rect(page_rect.x0, start_y, page_rect.x1, end_y or page_rect.y1),
        )
        return output_doc

    first_rect = source_doc[start_page - 1].rect
    _append_cropped_page(
        output_doc=output_doc,
        source_doc=source_doc,
        page_number=start_page,
        crop_rect=fitz.Rect(first_rect.x0, start_y, first_rect.x1, first_rect.y1),
    )

    middle_from = start_page + 1
    middle_to = end_page - 1 if end_y is not None else end_page
    if middle_from <= middle_to:
        output_doc.insert_pdf(
            source_doc,
            from_page=middle_from - 1,
            to_page=middle_to - 1,
        )

    if end_y is not None:
        last_rect = source_doc[end_page - 1].rect
        _append_cropped_page(
            output_doc=output_doc,
            source_doc=source_doc,
            page_number=end_page,
            crop_rect=fitz.Rect(last_rect.x0, last_rect.y0, last_rect.x1, end_y),
        )

    return output_doc


def _append_cropped_page(
    *,
    output_doc: Any,
    source_doc: Any,
    page_number: int,
    crop_rect: Any,
) -> None:
    if crop_rect.height <= 0 or crop_rect.width <= 0:
        raise LessonCutlineFullInputError("Cutline crop produced an empty page region.")

    page = source_doc[page_number - 1]
    original_crop = page.cropbox
    try:
        page.set_cropbox(crop_rect)
        output_doc.insert_pdf(source_doc, from_page=page_number - 1, to_page=page_number - 1)
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


def _validate_page_range(*, source_doc: Any, chunk: ChunkRecord) -> None:
    if chunk.start < 1 or chunk.end < chunk.start:
        raise LessonCutlineFullInputError(f"Invalid page range for {chunk.name}.")
    if chunk.end > source_doc.page_count:
        raise LessonCutlineFullInputError(
            f"Chunk {chunk.name} end page {chunk.end} is outside lesson PDF page count {source_doc.page_count}."
        )


def _get_pdf_page_height(*, source_pdf: Path, page_number: int) -> float:
    import fitz

    doc = fitz.open(str(source_pdf))
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise LessonCutlineFullInputError(
                f"Page {page_number} is outside lesson PDF page count {doc.page_count}."
            )
        return float(doc[page_number - 1].rect.height)
    finally:
        doc.close()


def _build_summary_payload(
    *,
    job_id: str,
    lesson_name: str,
    lesson_pdf_path: Path,
    processed_chunks: list[str],
    skipped_chunks: list[dict[str, str]],
    failed_chunks: list[dict[str, str]],
    updated_pdfs: list[str],
    boundaries: dict[str, CutlineBoundary],
    status: str,
    kaggle_request_id: str | None,
    kaggle_runs: int,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "source_lesson_pdf": str(lesson_pdf_path),
        "kaggle_mode": "batch",
        "kaggle_request_id": kaggle_request_id,
        "kaggle_runs": kaggle_runs,
        "processed_chunks": processed_chunks,
        "skipped_chunks": skipped_chunks,
        "failed_chunks": failed_chunks,
        "updated_pdfs": updated_pdfs,
        "cutline_boundaries": {
            chunk_name: {
                "page_number": boundary.page_number,
                "y_cut_image": boundary.y_cut_image,
                "image_height": boundary.image_height,
                "y_cut_pdf": boundary.y_cut_pdf,
                "match_score": boundary.match_score,
                "best_mode": boundary.best_mode,
            }
            for chunk_name, boundary in boundaries.items()
        },
        "status": status,
        "keyword_extracted": False,
        "keyword_paths": [],
    }


def _response_from_summary(
    summary_payload: dict[str, Any],
    summary_path: Path,
) -> LessonCutlineFullResponse:
    return LessonCutlineFullResponse(
        job_id=str(summary_payload["job_id"]),
        lesson_name=str(summary_payload["lesson_name"]),
        status=str(summary_payload["status"]),
        kaggle_mode=_optional_str(summary_payload.get("kaggle_mode")),
        kaggle_runs=_optional_int(summary_payload.get("kaggle_runs")),
        processed_chunks=list(summary_payload["processed_chunks"]),
        skipped_chunks=list(summary_payload["skipped_chunks"]),
        failed_chunks=list(summary_payload["failed_chunks"]),
        updated_pdfs=list(summary_payload["updated_pdfs"]),
        debug_summary_path=str(summary_path),
        keyword_extracted=bool(summary_payload.get("keyword_extracted")),
        keyword_paths=list(summary_payload.get("keyword_paths") or []),
        keyword_results=list(summary_payload.get("keyword_results") or []),
        keyword_error=_optional_str(summary_payload.get("keyword_error")),
    )


def _chunk_sort_key(chunk_name: str) -> tuple[int, str]:
    match = __import__("re").match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        return (10**9, chunk_name)
    return (int(match.group(1)), chunk_name)


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise LessonCutlineFullInputError(f"Required integer field is missing: {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LessonCutlineFullInputError(f"Required integer field is invalid: {field}") from exc


def _required_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LessonCutlineFullInputError(f"Required string field is missing: {field}")
    return value.strip()


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "LessonCutlineFullInputError",
    "process_full_lesson_cutlines",
]
