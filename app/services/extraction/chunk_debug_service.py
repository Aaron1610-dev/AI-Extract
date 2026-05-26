from __future__ import annotations

import re
from typing import Any

from app.pipeline.gemini_extract.pdf_utils import count_pdf_pages, split_pdf_range
from app.pipeline.gemini_extract.prompts.chunk_prompt import (
    build_chunk_prompt_start_head,
)
from app.pipeline.gemini_extract.topic_parser import parse_json_loose
from app.schemas.extraction import (
    ChunkApproveResponse,
    ChunkDebugResponse,
    ChunkItem,
    ChunkReviewResponse,
    LessonItem,
)
from app.services.extraction.job_service import get_job
from app.services.gemini.client import generate_with_pdf
from app.services.storage.workspace_service import (
    get_chunk_lesson_doc_dir,
    get_chunk_lesson_dir,
    get_chunk_json_path,
    get_chunk_pdf_path,
    get_chunks_approved_json_path,
    get_lesson_doc_path,
    get_lessons_approved_path,
    read_json,
    write_json,
)


_CHUNK_HEADING_RE = re.compile(r"^(?:\d+|[IVXLCDM]+)\.$")
NO_MAIN_CHUNK_TITLE = "KHÔNG CÓ MỤC CHÍNH"


class ChunkDebugPrerequisiteError(RuntimeError):
    pass


class ChunkReviewInputError(ValueError):
    pass


def extract_debug_chunks_for_lesson(
    job_id: str,
    lesson_name: str,
) -> ChunkDebugResponse:
    response = extract_chunks_for_lesson(job_id=job_id, lesson_name=lesson_name)
    return ChunkDebugResponse(
        job_id=response.job_id,
        lesson_name=response.lesson_name,
        chunks=response.chunks,
    )


def extract_chunks_for_lesson(
    job_id: str,
    lesson_name: str,
) -> ChunkReviewResponse:
    get_job(job_id)

    lesson = _read_approved_lesson(job_id, lesson_name)
    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    total_pages = count_pdf_pages(lesson_pdf_path)
    prompt = build_chunk_prompt_start_head(
        total_pages=total_pages,
        lesson_title=lesson.title,
    )
    raw_response_text = generate_with_pdf(
        prompt=prompt,
        pdf_path=lesson_pdf_path,
    )
    raw_payload = parse_json_loose(raw_response_text)
    chunks = _normalize_chunks(raw_payload, total_pages=total_pages)

    _write_review_chunks(
        job_id=job_id,
        lesson_name=lesson.name,
        chunks=chunks,
        lesson_pdf_path=lesson_pdf_path,
    )

    return ChunkReviewResponse(
        job_id=job_id,
        lesson_name=lesson.name,
        status="reviewing_chunks",
        chunks=chunks,
    )


def get_chunks_for_lesson(job_id: str, lesson_name: str) -> ChunkReviewResponse:
    get_job(job_id)
    chunks = _read_chunk_items(job_id=job_id, lesson_name=lesson_name)
    return ChunkReviewResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status="reviewing_chunks",
        chunks=chunks,
    )


def update_chunks_for_lesson(
    job_id: str,
    lesson_name: str,
    chunks: list[ChunkItem],
) -> ChunkReviewResponse:
    get_job(job_id)
    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    validated = _validate_review_chunks(chunks)
    _write_review_chunks(
        job_id=job_id,
        lesson_name=lesson_name,
        chunks=validated,
        lesson_pdf_path=lesson_pdf_path,
    )
    approved_path = get_chunks_approved_json_path(job_id, lesson_name)
    if approved_path.exists():
        approved_path.unlink()

    return ChunkReviewResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status="reviewing_chunks",
        chunks=validated,
    )


def approve_chunks_for_lesson(job_id: str, lesson_name: str) -> ChunkApproveResponse:
    get_job(job_id)
    chunks = _validate_review_chunks(
        _read_chunk_items(job_id=job_id, lesson_name=lesson_name)
    )
    approved_path = get_chunks_approved_json_path(job_id, lesson_name)
    payload = {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "status": "approved_chunks",
        "chunks": [_chunk_file_payload(chunk) for chunk in chunks],
    }
    write_json(approved_path, payload)
    return ChunkApproveResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status="approved_chunks",
        chunks=chunks,
        chunks_approved_path=str(approved_path),
    )


def _read_approved_lesson(job_id: str, lesson_name: str) -> LessonItem:
    lessons_approved_path = get_lessons_approved_path(job_id)
    if not lessons_approved_path.exists():
        raise ChunkDebugPrerequisiteError(
            "Lessons must be approved before chunk extraction."
        )

    payload = read_json(lessons_approved_path)
    if not isinstance(payload, list):
        raise ValueError(f"Expected approved lessons list in {lessons_approved_path}")

    for item in payload:
        if not isinstance(item, dict):
            continue

        if item.get("name") == lesson_name:
            return LessonItem.model_validate(item)

    raise FileNotFoundError(f"Lesson '{lesson_name}' was not found in approved lessons.")


def _read_chunk_items(*, job_id: str, lesson_name: str) -> list[ChunkItem]:
    lesson_chunk_dir = get_chunk_lesson_dir(job_id, lesson_name)
    if not lesson_chunk_dir.exists():
        raise FileNotFoundError(f"Chunk lesson directory was not found: {lesson_chunk_dir}")

    chunks: list[ChunkItem] = []
    for path in sorted(
        lesson_chunk_dir.glob("chunk_*.json"),
        key=lambda item: _chunk_sort_key(item.stem),
    ):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ChunkReviewInputError(f"Chunk JSON must contain an object: {path}")
        chunks.append(ChunkItem.model_validate(payload))

    if not chunks:
        raise FileNotFoundError(f"No chunk JSON files were found for lesson: {lesson_name}")

    return chunks


def _validate_review_chunks(chunks: list[ChunkItem]) -> list[ChunkItem]:
    if not chunks:
        raise ChunkReviewInputError("chunks must be non-empty.")

    if _is_no_heading_chunk_list(chunks):
        chunk = chunks[0]
        if chunk.start != 1:
            raise ChunkReviewInputError("No-heading chunk must start at page 1.")
        if chunk.end < 1:
            raise ChunkReviewInputError("No-heading chunk end must be >= 1.")
        if chunk.first_chunk is not None:
            raise ChunkReviewInputError("No-heading chunk must not have first_chunk.")
        if chunk.content_head is not None:
            raise ChunkReviewInputError("No-heading chunk must not have content_head.")
        return [
            ChunkItem(
                name="chunk_01",
                start=1,
                end=int(chunk.end),
                heading=None,
                title=NO_MAIN_CHUNK_TITLE,
            )
        ]

    validated: list[ChunkItem] = []
    for index, chunk in enumerate(chunks, start=1):
        expected_name = f"chunk_{index:02d}"
        if chunk.name != expected_name:
            raise ChunkReviewInputError(
                f"Chunk names must be sequential; expected {expected_name}."
            )
        if chunk.start > chunk.end:
            raise ChunkReviewInputError(f"{chunk.name} start must be <= end.")
        if not chunk.heading or not _is_valid_chunk_heading(chunk.heading.strip()):
            raise ChunkReviewInputError(
                f"{chunk.name} heading must be numeric or Roman heading like '1.' or 'I.'."
            )
        if not chunk.title.strip():
            raise ChunkReviewInputError(f"{chunk.name} title must not be empty.")

        if index == 1:
            if chunk.first_chunk is not True:
                raise ChunkReviewInputError("chunk_01 must have first_chunk=true.")
            if chunk.content_head is not None:
                raise ChunkReviewInputError("chunk_01 must not have content_head.")
            validated.append(
                ChunkItem(
                    name=chunk.name,
                    start=int(chunk.start),
                    end=int(chunk.end),
                    first_chunk=True,
                    heading=chunk.heading.strip(),
                    title=chunk.title.strip(),
                )
            )
            continue

        if chunk.first_chunk is not None:
            raise ChunkReviewInputError(f"{chunk.name} must not have first_chunk.")
        if not isinstance(chunk.content_head, bool):
            raise ChunkReviewInputError(f"{chunk.name} must have content_head true/false.")
        validated.append(
            ChunkItem(
                name=chunk.name,
                start=int(chunk.start),
                end=int(chunk.end),
                content_head=chunk.content_head,
                heading=chunk.heading.strip(),
                title=chunk.title.strip(),
            )
        )

    return validated


def _is_no_heading_chunk_list(chunks: list[ChunkItem]) -> bool:
    if len(chunks) != 1:
        return False
    chunk = chunks[0]
    return (
        chunk.name == "chunk_01"
        and chunk.heading is None
        and chunk.title == NO_MAIN_CHUNK_TITLE
    )


def _write_review_chunks(
    *,
    job_id: str,
    lesson_name: str,
    chunks: list[ChunkItem],
    lesson_pdf_path: Any,
) -> None:
    validated = _validate_review_chunks(chunks)
    lesson_chunk_dir = get_chunk_lesson_dir(job_id, lesson_name)
    doc_dir = get_chunk_lesson_doc_dir(job_id, lesson_name)
    valid_names = {chunk.name for chunk in validated}

    for stale_path in lesson_chunk_dir.glob("chunk_*.json"):
        if stale_path.stem not in valid_names:
            stale_path.unlink()
    if doc_dir.exists():
        for stale_pdf in doc_dir.glob("chunk_*.pdf"):
            if stale_pdf.stem not in valid_names:
                stale_pdf.unlink()

    for chunk in validated:
        write_json(
            get_chunk_json_path(job_id, lesson_name, chunk.name),
            _chunk_file_payload(chunk),
        )
        split_pdf_range(
            source_pdf=lesson_pdf_path,
            output_pdf=get_chunk_pdf_path(job_id, lesson_name, chunk.name),
            start_page=chunk.start,
            end_page=chunk.end,
        )


def _chunk_file_payload(chunk: ChunkItem) -> dict[str, Any]:
    payload = chunk.model_dump(mode="json", exclude_none=False)
    return {
        key: value
        for key, value in payload.items()
        if value is not None or key == "heading"
    }


def _normalize_chunks(payload: dict[str, Any], total_pages: int) -> list[ChunkItem]:
    raw_chunks = payload.get("chunks")
    if not isinstance(raw_chunks, list):
        raw_chunks = []

    candidates: list[dict[str, Any]] = []
    for raw_chunk in raw_chunks:
        if not isinstance(raw_chunk, dict):
            continue

        heading = _clean_string(raw_chunk.get("heading"))
        title = _clean_string(raw_chunk.get("title"))
        start = _to_int(raw_chunk.get("start"))

        if (
            not heading
            or not _is_valid_chunk_heading(heading)
            or not title
            or start is None
        ):
            continue

        start = max(1, min(start, total_pages))
        candidates.append(
            {
                "start": start,
                "heading": heading,
                "title": title,
                "content_head": _to_bool(raw_chunk.get("content_head")),
            }
        )

    candidates.sort(key=lambda item: item["start"])
    if not candidates:
        return [
            ChunkItem(
                name="chunk_01",
                start=1,
                end=max(1, total_pages),
                heading=None,
                title=NO_MAIN_CHUNK_TITLE,
            )
        ]

    chunks: list[ChunkItem] = []

    for index, candidate in enumerate(candidates):
        next_candidate = (
            candidates[index + 1]
            if index + 1 < len(candidates)
            else None
        )
        end = _calculate_end(
            current_start=candidate["start"],
            next_candidate=next_candidate,
            total_pages=total_pages,
        )

        if index == 0:
            chunks.append(
                ChunkItem(
                    name="chunk_01",
                    start=candidate["start"],
                    end=end,
                    first_chunk=True,
                    heading=candidate["heading"],
                    title=candidate["title"],
                )
            )
            continue

        chunks.append(
            ChunkItem(
                name=f"chunk_{index + 1:02d}",
                start=candidate["start"],
                end=end,
                content_head=bool(candidate["content_head"]),
                heading=candidate["heading"],
                title=candidate["title"],
            )
        )

    return chunks


def _calculate_end(
    *,
    current_start: int,
    next_candidate: dict[str, Any] | None,
    total_pages: int,
) -> int:
    if next_candidate is None:
        return total_pages

    next_start = int(next_candidate["start"])
    if bool(next_candidate.get("content_head")):
        return max(current_start, min(next_start, total_pages))

    return max(current_start, min(next_start - 1, total_pages))


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def _is_valid_chunk_heading(value: str) -> bool:
    return _CHUNK_HEADING_RE.match(value) is not None


def _chunk_sort_key(chunk_name: str) -> tuple[int, str]:
    match = re.match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        return (10**9, chunk_name)
    return (int(match.group(1)), chunk_name)


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return int(text)
    except ValueError:
        return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}

    return False
