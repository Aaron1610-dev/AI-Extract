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
    get_chunk_keyword_raw_path,
    get_chunk_lesson_dir,
    get_keyword_summary_path,
    get_lesson_doc_path,
    get_lesson_keyword_path,
    get_lesson_keyword_raw_path,
    get_lessons_approved_json_path,
    read_json,
    write_json,
)
from app.utils.json_utils import extract_json, normalize_for_compare


SINGLE_CHUNK_KEYWORD_LIMIT = 10
MULTI_CHUNK_KEYWORD_LIMIT = 5


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

    if len(chunks) == 1:
        strategy = "single_chunk_lesson_keywords"
        keyword_limit = SINGLE_CHUNK_KEYWORD_LIMIT
        sources = [
            {
                "source_type": "lesson",
                "source_name": lesson_name,
                "source_title": _source_title(lesson),
                "source_pdf": lesson_pdf_path,
                "raw_path": get_lesson_keyword_raw_path(job_id, lesson_name),
                "keywords_path": get_lesson_keyword_path(job_id, lesson_name),
            }
        ]
    else:
        strategy = "per_chunk_keywords"
        keyword_limit = MULTI_CHUNK_KEYWORD_LIMIT
        sources = []
        for chunk in chunks:
            chunk_name = str(chunk["name"])
            chunk_pdf_path = get_chunk_doc_dir(job_id, lesson_name) / f"{chunk_name}.pdf"
            if not chunk_pdf_path.exists():
                raise FileNotFoundError(f"Chunk PDF was not found: {chunk_pdf_path}")
            sources.append(
                {
                    "source_type": "chunk",
                    "source_name": chunk_name,
                    "source_title": _source_title(chunk),
                    "source_pdf": chunk_pdf_path,
                    "raw_path": get_chunk_keyword_raw_path(job_id, lesson_name, chunk_name),
                    "keywords_path": get_chunk_keyword_path(job_id, lesson_name, chunk_name),
                }
            )

    results: list[dict[str, Any]] = []
    summary_sources: list[dict[str, str]] = []
    for source in sources:
        raw_payload, normalized = _extract_source_keywords(
            source_type=str(source["source_type"]),
            source_name=str(source["source_name"]),
            source_title=source.get("source_title"),
            source_pdf=Path(source["source_pdf"]),
            keyword_limit=keyword_limit,
            model=model,
        )
        write_json(Path(source["raw_path"]), raw_payload)
        write_json(Path(source["keywords_path"]), normalized)

        results.append(
            {
                "source_type": normalized["source_type"],
                "source_name": normalized["source_name"],
                "keywords": normalized["keywords"],
            }
        )
        summary_sources.append(
            {
                "source_type": str(source["source_type"]),
                "source_name": str(source["source_name"]),
                "source_pdf": str(source["source_pdf"]),
                "keywords_path": str(source["keywords_path"]),
            }
        )

    summary_path = get_keyword_summary_path(job_id, lesson_name)
    summary_payload = {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "lesson_title": _source_title(lesson),
        "chunk_count": len(chunks),
        "strategy": strategy,
        "keyword_limit": keyword_limit,
        "sources": summary_sources,
    }
    write_json(summary_path, summary_payload)

    return LessonKeywordDebugResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_count=len(chunks),
        strategy=strategy,
        keyword_limit=keyword_limit,
        results=results,
        summary_path=str(summary_path),
    )


def _extract_source_keywords(
    *,
    source_type: str,
    source_name: str,
    source_title: str | None,
    source_pdf: Path,
    keyword_limit: int,
    model: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = build_keyword_prompt(
        keyword_limit=keyword_limit,
        source_type=source_type,
        source_title=source_title,
    )
    raw_response_text = generate_with_pdf(
        prompt=prompt,
        pdf_path=source_pdf,
        model=model,
    )
    parsed = extract_json(raw_response_text)
    raw_payload = {
        "source_type": source_type,
        "source_name": source_name,
        "source_title": source_title,
        "source_pdf": str(source_pdf),
        "keyword_limit": keyword_limit,
        "raw_response_text": raw_response_text,
        "raw_payload": parsed,
    }
    normalized = normalize_keyword_payload(
        payload=parsed,
        source_type=source_type,
        source_name=source_name,
        keyword_limit=keyword_limit,
    )
    return raw_payload, normalized


def normalize_keyword_payload(
    *,
    payload: dict[str, Any],
    source_type: str,
    source_name: str,
    keyword_limit: int,
) -> dict[str, Any]:
    raw_keywords = payload.get("keywords") if isinstance(payload, dict) else []
    if not isinstance(raw_keywords, list):
        raw_keywords = []

    keywords: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_keywords:
        keyword: str | None = None
        reason: str | None = None
        confidence: float | None = None

        if isinstance(item, dict):
            raw_keyword = item.get("keyword")
            if isinstance(raw_keyword, str):
                keyword = raw_keyword.strip()
            raw_reason = item.get("reason")
            if isinstance(raw_reason, str):
                reason = raw_reason.strip() or None
            confidence = _optional_float(item.get("confidence"))
        elif isinstance(item, str):
            keyword = item.strip()

        if not keyword:
            continue

        key = normalize_for_compare(keyword)
        if not key or key in seen:
            continue

        seen.add(key)
        keywords.append(
            {
                "keyword": keyword,
                "reason": reason,
                "confidence": confidence,
            }
        )
        if len(keywords) >= keyword_limit:
            break

    return {
        "source_type": source_type,
        "source_name": source_name,
        "keyword_limit": keyword_limit,
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
    parts = [str(value).strip() for value in [heading, title] if isinstance(value, str) and value.strip()]
    return " ".join(parts) if parts else None


def _chunk_sort_key(chunk_name: str) -> tuple[int, str]:
    match = __import__("re").match(r"^chunk_(\d+)$", chunk_name)
    if not match:
        return (10**9, chunk_name)
    return (int(match.group(1)), chunk_name)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "KeywordDebugInputError",
    "extract_keywords_for_lesson_debug",
    "normalize_keyword_payload",
]
