from __future__ import annotations

from typing import Any

from app.pipeline.gemini_extract.prompts.chunk_prompt import build_chunk_prompt
from app.pipeline.gemini_extract.topic_parser import parse_json_loose
from app.schemas.extraction import ChunkDebugResponse, ChunkItem, LessonItem
from app.services.extraction.job_service import get_job
from app.services.gemini.client import generate_with_pdf
from app.services.storage.workspace_service import (
    get_chunk_debug_json_path,
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

    prompt = build_chunk_prompt(
        lesson_name=lesson.name,
        lesson_title=lesson.title,
    )
    raw_response_text = generate_with_pdf(
        prompt=prompt,
        pdf_path=lesson_pdf_path,
    )
    raw_payload = parse_json_loose(raw_response_text)
    chunks = _normalize_chunks(raw_payload, lesson)

    debug_payload = {
        "job_id": job_id,
        "lesson_name": lesson.name,
        "lesson_title": lesson.title,
        "source": "gemini",
        "raw_response_text": raw_response_text,
        "raw_payload": raw_payload,
        "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
    }
    write_json(get_chunk_debug_json_path(job_id, lesson.name), debug_payload)

    return ChunkDebugResponse(
        job_id=job_id,
        lesson_name=lesson.name,
        lesson_title=lesson.title,
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


def _normalize_chunks(payload: dict[str, Any], lesson: LessonItem) -> list[ChunkItem]:
    raw_chunks = payload.get("chunks")
    if not isinstance(raw_chunks, list):
        raw_chunks = []

    chunks: list[ChunkItem] = []
    for raw_chunk in raw_chunks:
        if not isinstance(raw_chunk, dict):
            continue

        title = _clean_string(raw_chunk.get("title"))
        heading = _clean_string(raw_chunk.get("heading"))
        if not title:
            continue

        start_page = _to_int(raw_chunk.get("start_page_in_lesson"))
        end_page = _to_int(raw_chunk.get("end_page_in_lesson"))

        if end_page is None and start_page is not None:
            end_page = start_page

        chunks.append(
            ChunkItem(
                name=f"chunk_{len(chunks) + 1:02d}",
                lesson_name=lesson.name,
                lesson_title=lesson.title,
                topic_name=lesson.topic_name,
                topic_title=lesson.topic_title,
                heading=heading,
                title=title,
                start_page_in_lesson=start_page,
                end_page_in_lesson=end_page,
                summary=_clean_string(raw_chunk.get("summary")),
            )
        )

    return chunks


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
