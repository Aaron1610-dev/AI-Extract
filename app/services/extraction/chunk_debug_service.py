from __future__ import annotations

from typing import Any

from app.pipeline.gemini_extract.pdf_utils import count_pdf_pages, split_pdf_range
from app.pipeline.gemini_extract.prompts.chunk_prompt import (
    build_chunk_prompt_start_head,
)
from app.pipeline.gemini_extract.topic_parser import parse_json_loose
from app.schemas.extraction import ChunkDebugResponse, ChunkItem, LessonItem
from app.services.extraction.job_service import get_job
from app.services.gemini.client import generate_with_pdf
from app.services.storage.workspace_service import (
    get_chunk_json_path,
    get_chunk_pdf_path,
    get_lesson_doc_path,
    get_lessons_approved_path,
    read_json,
    write_json,
)


class ChunkDebugPrerequisiteError(RuntimeError):
    pass


def extract_debug_chunks_for_lesson(
    job_id: str,
    lesson_name: str,
) -> ChunkDebugResponse:
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

    for chunk in chunks:
        chunk_payload = chunk.model_dump(mode="json", exclude_none=True)
        write_json(
            get_chunk_json_path(job_id, lesson.name, chunk.name),
            chunk_payload,
        )
        split_pdf_range(
            source_pdf=lesson_pdf_path,
            output_pdf=get_chunk_pdf_path(job_id, lesson.name, chunk.name),
            start_page=chunk.start,
            end_page=chunk.end,
        )

    return ChunkDebugResponse(
        job_id=job_id,
        lesson_name=lesson.name,
        chunks=chunks,
    )


def _read_approved_lesson(job_id: str, lesson_name: str) -> LessonItem:
    lessons_approved_path = get_lessons_approved_path(job_id)
    if not lessons_approved_path.exists():
        raise ChunkDebugPrerequisiteError(
            "Lessons must be approved before debug chunk extraction."
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

        if not heading or not title or start is None:
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
