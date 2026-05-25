from __future__ import annotations

from pathlib import Path
from typing import Any

from app.pipeline.gemini_extract.prompts.keyword_prompt import build_keyword_prompt
from app.schemas.extraction import LessonKeywordDebugResponse
from app.services.extraction.job_service import get_job
from app.services.gemini.client import generate_with_pdf
from app.services.storage.workspace_service import (
    get_chunk_doc_dir,
    get_chunk_keyword_path,
    get_chunk_lesson_dir,
    get_chunk_lesson_keyword_dir,
    get_lesson_doc_path,
    get_lessons_approved_json_path,
    read_json,
    write_json,
)
from app.utils.json_utils import extract_json, normalize_for_compare


SINGLE_CHUNK_KEYWORD_COUNT = 10
MULTI_CHUNK_KEYWORD_COUNT = 5


class KeywordDebugInputError(ValueError):
    pass


def extract_keywords_for_lesson_debug(
    job_id: str,
    lesson_name: str,
    *,
    model: str | None = None,
) -> LessonKeywordDebugResponse:
    get_job(job_id)

    lesson = _get_approved_lesson(job_id=job_id, lesson_name=lesson_name)
    lesson_pdf_path = get_lesson_doc_path(job_id, lesson_name)
    if not lesson_pdf_path.exists():
        raise FileNotFoundError(f"Lesson PDF was not found: {lesson_pdf_path}")

    chunks = _load_lesson_chunks(job_id=job_id, lesson_name=lesson_name)
    if not chunks:
        raise KeywordDebugInputError(f"No chunk JSON files were found for lesson: {lesson_name}")

    get_chunk_lesson_keyword_dir(job_id, lesson_name).mkdir(parents=True, exist_ok=True)

    sources: list[dict[str, Any]] = []
    if len(chunks) == 1:
        chunk_name = str(chunks[0]["name"])
        sources.append(
            {
                "source_type": "lesson",
                "chunk_name": chunk_name,
                "source_title": _source_title(lesson),
                "source_pdf": lesson_pdf_path,
                "keyword_count": SINGLE_CHUNK_KEYWORD_COUNT,
                "keyword_path": get_chunk_keyword_path(job_id, lesson_name, chunk_name),
            }
        )
    else:
        for chunk in chunks:
            chunk_name = str(chunk["name"])
            chunk_pdf_path = get_chunk_doc_dir(job_id, lesson_name) / f"{chunk_name}.pdf"
            if not chunk_pdf_path.exists():
                raise FileNotFoundError(f"Chunk PDF was not found: {chunk_pdf_path}")

            sources.append(
                {
                    "source_type": "chunk",
                    "chunk_name": chunk_name,
                    "source_title": _source_title(chunk),
                    "source_pdf": chunk_pdf_path,
                    "keyword_count": MULTI_CHUNK_KEYWORD_COUNT,
                    "keyword_path": get_chunk_keyword_path(job_id, lesson_name, chunk_name),
                }
            )

    results: list[dict[str, Any]] = []
    for source in sources:
        keyword_count = int(source["keyword_count"])
        normalized = _extract_source_keywords(
            source_type=str(source["source_type"]),
            chunk_name=str(source["chunk_name"]),
            source_title=source.get("source_title"),
            source_pdf=Path(source["source_pdf"]),
            keyword_count=keyword_count,
            model=model,
        )
        keyword_path = Path(source["keyword_path"])
        write_json(keyword_path, normalized)

        results.append(
            {
                "chunk_name": normalized["chunk_name"],
                "keyword_count": normalized["keyword_count"],
                "keywords": normalized["keywords"],
                "keyword_path": str(keyword_path),
            }
        )

    return LessonKeywordDebugResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_count=len(chunks),
        results=results,
    )


def _extract_source_keywords(
    *,
    source_type: str,
    chunk_name: str,
    source_title: str | None,
    source_pdf: Path,
    keyword_count: int,
    model: str | None,
) -> dict[str, Any]:
    prompt = build_keyword_prompt(
        keyword_limit=keyword_count,
        source_type=source_type,
        source_title=source_title,
    )
    raw_response_text = generate_with_pdf(
        prompt=prompt,
        pdf_path=source_pdf,
        model=model,
    )
    parsed = extract_json(raw_response_text)
    return normalize_keyword_payload(
        payload=parsed,
        chunk_name=chunk_name,
        keyword_count=keyword_count,
    )


def normalize_keyword_payload(
    *,
    payload: dict[str, Any],
    chunk_name: str,
    keyword_count: int,
) -> dict[str, Any]:
    raw_keywords = payload.get("keywords") if isinstance(payload, dict) else []
    if not isinstance(raw_keywords, list):
        raw_keywords = []

    keywords: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_keywords:
        keyword: str | None = None

        if isinstance(item, dict):
            raw_keyword = item.get("keyword_name") or item.get("keyword")
            if isinstance(raw_keyword, str):
                keyword = raw_keyword.strip()
        elif isinstance(item, str):
            keyword = item.strip()

        if not keyword:
            continue

        key = normalize_for_compare(keyword)
        if not key or key in seen:
            continue

        seen.add(key)
        keywords.append({"keyword_name": keyword})
        if len(keywords) >= keyword_count:
            break

    return {
        "chunk_name": chunk_name,
        "keyword_count": keyword_count,
        "keywords": keywords,
    }


def _get_approved_lesson(*, job_id: str, lesson_name: str) -> dict[str, Any]:
    lessons_path = get_lessons_approved_json_path(job_id)
    if not lessons_path.exists():
        raise FileNotFoundError(f"Approved lessons JSON was not found: {lessons_path}")

    lessons = read_json(lessons_path)
    if not isinstance(lessons, list):
        raise ValueError(f"Expected lessons list in {lessons_path}")

    for lesson in lessons:
        if isinstance(lesson, dict) and lesson.get("name") == lesson_name:
            return lesson

    raise FileNotFoundError(f"Lesson '{lesson_name}' was not found in approved lessons.")


def _load_lesson_chunks(*, job_id: str, lesson_name: str) -> list[dict[str, Any]]:
    lesson_chunk_dir = get_chunk_lesson_dir(job_id, lesson_name)
    if not lesson_chunk_dir.exists():
        raise FileNotFoundError(f"Chunk lesson directory was not found: {lesson_chunk_dir}")

    chunks: list[dict[str, Any]] = []
    for path in sorted(lesson_chunk_dir.glob("chunk_*.json"), key=lambda item: _chunk_sort_key(item.stem)):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise KeywordDebugInputError(f"Chunk JSON must contain an object: {path}")
        item = dict(payload)
        item["name"] = path.stem
        chunks.append(item)
    return chunks


def _source_title(payload: dict[str, Any]) -> str | None:
    heading = payload.get("heading")
    title = payload.get("title")
    parts = [
        str(value).strip()
        for value in [heading, title]
        if isinstance(value, str) and value.strip()
    ]
    return " ".join(parts) if parts else None


def _chunk_sort_key(chunk_name: str) -> tuple[int, str]:
    match = __import__("re").match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        return (10**9, chunk_name)
    return (int(match.group(1)), chunk_name)


__all__ = [
    "KeywordDebugInputError",
    "extract_keywords_for_lesson_debug",
    "normalize_keyword_payload",
]
