from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from datetime import UTC, datetime

from app.pipeline.gemini_extract.prompts.keyword_prompt import (
    build_keyword_prompt,
    build_keyword_retry_prompt,
)
from app.schemas.extraction import (
    KeywordChunkExtractResponse,
    LessonKeywordApproveResponse,
    LessonKeywordDebugResponse,
    LessonKeywordDebugResult,
    LessonKeywordReviewResponse,
)
from app.services.extraction.job_service import get_job
from app.services.gemini.client import generate_with_pdf
from app.services.storage.workspace_service import (
    get_chunk_doc_dir,
    get_chunk_json_path,
    get_chunk_keyword_path,
    get_chunk_lesson_dir,
    get_chunk_lesson_keyword_dir,
    get_keywords_approved_json_path,
    get_lesson_doc_path,
    get_lessons_approved_json_path,
    read_json,
    write_json,
)
from app.utils.json_utils import extract_json, normalize_for_compare


SINGLE_CHUNK_KEYWORD_COUNT = 10
MULTI_CHUNK_KEYWORD_COUNT = 5
MAX_KEYWORD_RETRIES = 3

logger = logging.getLogger(__name__)


class KeywordDebugInputError(ValueError):
    pass


class KeywordExtractionCountError(RuntimeError):
    pass


class KeywordReviewInputError(ValueError):
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

    pending_results: list[tuple[Path, dict[str, Any]]] = []
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
        pending_results.append((keyword_path, normalized))

    results: list[dict[str, Any]] = []
    for keyword_path, normalized in pending_results:
        write_json(keyword_path, normalized)
        results.append({
            "chunk_name": normalized["chunk_name"],
            "keyword_count": normalized["keyword_count"],
            "keywords": normalized["keywords"],
            "keyword_path": str(keyword_path),
        })

    return LessonKeywordDebugResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_count=len(chunks),
        results=results,
    )


def get_keywords_for_lesson(
    job_id: str,
    lesson_name: str,
) -> LessonKeywordReviewResponse:
    get_job(job_id)
    _get_approved_lesson(job_id=job_id, lesson_name=lesson_name)
    chunks = _load_lesson_chunks(job_id=job_id, lesson_name=lesson_name)
    results = _read_keyword_results(job_id=job_id, lesson_name=lesson_name)
    result_chunks = {result.chunk_name for result in results}
    missing_chunks = [
        str(chunk["name"])
        for chunk in chunks
        if str(chunk["name"]) not in result_chunks
    ]
    approved_path = get_keywords_approved_json_path(job_id, lesson_name)
    return LessonKeywordReviewResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status=(
            "approved_keywords"
            if approved_path.exists() and not missing_chunks
            else "reviewing_keywords"
        ),
        results=results,
        missing_chunks=missing_chunks,
    )


def extract_keyword_for_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
    *,
    model: str | None = None,
) -> KeywordChunkExtractResponse:
    get_job(job_id)

    lesson = _get_approved_lesson(job_id=job_id, lesson_name=lesson_name)
    chunk_path = get_chunk_json_path(job_id, lesson_name, chunk_name)
    if not chunk_path.exists():
        raise FileNotFoundError(f"Chunk JSON was not found: {chunk_path}")

    chunks = _load_lesson_chunks(job_id=job_id, lesson_name=lesson_name)
    selected_chunk = next(
        (chunk for chunk in chunks if str(chunk.get("name")) == chunk_name),
        None,
    )
    if selected_chunk is None:
        raise FileNotFoundError(f"Chunk '{chunk_name}' was not found in lesson: {lesson_name}")

    if len(chunks) == 1:
        source_type = "lesson"
        source_title = _source_title(lesson)
        source_pdf = get_lesson_doc_path(job_id, lesson_name)
        keyword_count = SINGLE_CHUNK_KEYWORD_COUNT
    else:
        source_type = "chunk"
        source_title = _source_title(selected_chunk)
        source_pdf = get_chunk_doc_dir(job_id, lesson_name) / f"{chunk_name}.pdf"
        keyword_count = MULTI_CHUNK_KEYWORD_COUNT

    if not source_pdf.exists():
        raise FileNotFoundError(f"Keyword source PDF was not found: {source_pdf}")

    normalized = _extract_source_keywords(
        source_type=source_type,
        chunk_name=chunk_name,
        source_title=source_title,
        source_pdf=source_pdf,
        keyword_count=keyword_count,
        model=model,
    )
    if normalized["keyword_count"] != len(normalized["keywords"]):
        raise KeywordExtractionCountError(
            f"Keyword extraction failed: keyword_count does not equal len(keywords) for {chunk_name}."
        )

    keyword_path = get_chunk_keyword_path(job_id, lesson_name, chunk_name)
    _write_keyword_json_atomic(keyword_path, normalized)

    return KeywordChunkExtractResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        chunk_name=chunk_name,
        keyword_count=int(normalized["keyword_count"]),
        keywords=normalized["keywords"],
        keyword_path=str(keyword_path),
    )


def update_keywords_for_lesson(
    job_id: str,
    lesson_name: str,
    results: list[LessonKeywordDebugResult],
) -> LessonKeywordReviewResponse:
    get_job(job_id)
    validated = _validate_keyword_results(
        job_id=job_id,
        lesson_name=lesson_name,
        results=results,
    )
    for result in validated:
        keyword_path = get_chunk_keyword_path(job_id, lesson_name, result.chunk_name)
        write_json(
            keyword_path,
            {
                "chunk_name": result.chunk_name,
                "keyword_count": result.keyword_count,
                "keywords": [
                    {"keyword_name": item.keyword_name}
                    for item in result.keywords
                ],
            },
        )

    approved_path = get_keywords_approved_json_path(job_id, lesson_name)
    if approved_path.exists():
        approved_path.unlink()

    return LessonKeywordReviewResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status="reviewing_keywords",
        results=_read_keyword_results(job_id=job_id, lesson_name=lesson_name),
    )


def approve_keywords_for_lesson(
    job_id: str,
    lesson_name: str,
) -> LessonKeywordApproveResponse:
    get_job(job_id)
    results = _validate_keyword_results(
        job_id=job_id,
        lesson_name=lesson_name,
        results=_read_keyword_results(job_id=job_id, lesson_name=lesson_name),
    )
    approved_at = datetime.now(UTC).isoformat()
    approved_path = get_keywords_approved_json_path(job_id, lesson_name)
    payload = {
        "job_id": job_id,
        "lesson_name": lesson_name,
        "status": "approved_keywords",
        "approved_at": approved_at,
        "results": [
            {
                "chunk_name": result.chunk_name,
                "keyword_count": result.keyword_count,
                "keywords": [
                    {"keyword_name": item.keyword_name}
                    for item in result.keywords
                ],
                "keyword_path": result.keyword_path,
            }
            for result in results
        ],
    }
    write_json(approved_path, payload)
    return LessonKeywordApproveResponse(
        job_id=job_id,
        lesson_name=lesson_name,
        status="approved_keywords",
        approved_at=approved_at,
        results=results,
        keywords_approved_path=str(approved_path),
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
    raw_keywords = parsed.get("keywords") if isinstance(parsed, dict) else []
    keywords, debug = _normalize_keywords_with_debug(raw_keywords)
    _log_keyword_normalization_debug(
        chunk_name=chunk_name,
        stage="initial",
        attempt=1,
        retry_attempt=0,
        raw_count=debug["raw_count"],
        normalized_count=len(keywords),
        removed=debug["removed"],
    )
    if len(keywords) >= keyword_count:
        keywords = keywords[:keyword_count]
        return {
            "chunk_name": chunk_name,
            "keyword_count": keyword_count,
            "keywords": keywords,
        }

    for retry_attempt in range(1, MAX_KEYWORD_RETRIES + 1):
        if len(keywords) == keyword_count:
            break

        retry_prompt = build_keyword_retry_prompt(
            keyword_limit=keyword_count,
            source_type=source_type,
            source_title=source_title,
            existing_keywords=[item["keyword_name"] for item in keywords],
        )
        retry_response_text = generate_with_pdf(
            prompt=retry_prompt,
            pdf_path=source_pdf,
            model=model,
        )
        retry_parsed = extract_json(retry_response_text)
        retry_raw_keywords = retry_parsed.get("keywords") if isinstance(retry_parsed, dict) else []
        retry_keywords, retry_debug = _normalize_keywords_with_debug(retry_raw_keywords)
        _log_keyword_normalization_debug(
            chunk_name=chunk_name,
            stage="completion",
            attempt=retry_attempt + 1,
            retry_attempt=retry_attempt,
            raw_count=retry_debug["raw_count"],
            normalized_count=len(retry_keywords),
            removed=retry_debug["removed"],
        )
        before_merge_count = len(keywords)
        keywords = _merge_keywords(keywords, retry_keywords, keyword_count)
        logger.info(
            "Keyword extraction merge: chunk=%s retry_attempt=%s before=%s completion_normalized=%s after=%s target=%s",
            chunk_name,
            retry_attempt,
            before_merge_count,
            len(retry_keywords),
            len(keywords),
            keyword_count,
        )

    if len(keywords) != keyword_count:
        logger.error(
            "Keyword extraction failed count check: chunk=%s target=%s normalized_count=%s retries=%s",
            chunk_name,
            keyword_count,
            len(keywords),
            MAX_KEYWORD_RETRIES,
        )
        raise KeywordExtractionCountError(
            f"Keyword extraction failed: expected exactly {keyword_count} keywords for {chunk_name}, "
            f"got {len(keywords)} after retries."
        )

    return {
        "chunk_name": chunk_name,
        "keyword_count": keyword_count,
        "keywords": keywords,
    }


def normalize_keyword_payload(
    *,
    payload: dict[str, Any],
    chunk_name: str,
    keyword_count: int,
) -> dict[str, Any]:
    keywords = _normalize_keywords(payload.get("keywords") if isinstance(payload, dict) else [])[:keyword_count]
    if len(keywords) != keyword_count:
        raise KeywordExtractionCountError(
            f"Keyword extraction failed: expected exactly {keyword_count} keywords for {chunk_name}, "
            f"got {len(keywords)}."
        )
    return {
        "chunk_name": chunk_name,
        "keyword_count": keyword_count,
        "keywords": keywords,
    }


def _read_keyword_results(
    *,
    job_id: str,
    lesson_name: str,
) -> list[LessonKeywordDebugResult]:
    keyword_dir = get_chunk_lesson_keyword_dir(job_id, lesson_name)
    if not keyword_dir.exists():
        return []

    results: list[LessonKeywordDebugResult] = []
    for path in sorted(keyword_dir.glob("keyword_chunk_*.json"), key=lambda item: _chunk_sort_key(item.stem.replace("keyword_", ""))):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise KeywordReviewInputError(f"Keyword JSON must contain an object: {path}")
        results.append(
            LessonKeywordDebugResult(
                chunk_name=str(payload.get("chunk_name") or path.stem.replace("keyword_", "")),
                keyword_count=_required_int(payload, "keyword_count"),
                keywords=_normalize_keywords_strict(payload.get("keywords")),
                keyword_path=str(path),
            )
        )

    return results


def _write_keyword_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.tmp{path.suffix}")
    if temp_path.exists():
        temp_path.unlink()
    try:
        write_json(temp_path, payload)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _validate_keyword_results(
    *,
    job_id: str,
    lesson_name: str,
    results: list[LessonKeywordDebugResult],
) -> list[LessonKeywordDebugResult]:
    if not results:
        raise KeywordReviewInputError("results must be non-empty.")

    chunks = _load_lesson_chunks(job_id=job_id, lesson_name=lesson_name)
    if not chunks:
        raise KeywordReviewInputError(f"No chunk JSON files were found for lesson: {lesson_name}")
    chunk_names = {str(chunk["name"]) for chunk in chunks}
    expected_count = (
        SINGLE_CHUNK_KEYWORD_COUNT
        if len(chunks) == 1
        else MULTI_CHUNK_KEYWORD_COUNT
    )

    seen_chunks: set[str] = set()
    validated: list[LessonKeywordDebugResult] = []
    for result in results:
        chunk_name = result.chunk_name.strip()
        if chunk_name not in chunk_names:
            raise KeywordReviewInputError(f"Unknown chunk_name: {chunk_name}")
        if chunk_name in seen_chunks:
            raise KeywordReviewInputError(f"Duplicate keyword result for {chunk_name}.")
        seen_chunks.add(chunk_name)

        keywords = _normalize_keywords_strict(
            [{"keyword_name": item.keyword_name} for item in result.keywords]
        )
        if result.keyword_count != len(keywords):
            raise KeywordReviewInputError(
                f"{chunk_name} keyword_count must equal len(keywords)."
            )
        if result.keyword_count != expected_count:
            raise KeywordReviewInputError(
                f"{chunk_name} must have exactly {expected_count} keywords."
            )
        validated.append(
            LessonKeywordDebugResult(
                chunk_name=chunk_name,
                keyword_count=expected_count,
                keywords=keywords,
                keyword_path=str(get_chunk_keyword_path(job_id, lesson_name, chunk_name)),
            )
        )

    if seen_chunks != chunk_names:
        missing = sorted(chunk_names - seen_chunks)
        raise KeywordReviewInputError(
            f"Keyword results are missing chunks: {', '.join(missing)}."
        )

    return sorted(validated, key=lambda item: _chunk_sort_key(item.chunk_name))


def _normalize_keywords_strict(raw_keywords: Any) -> list[dict[str, str]]:
    if not isinstance(raw_keywords, list):
        raise KeywordReviewInputError("keywords must be a list.")

    keywords: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_keywords:
        if not isinstance(item, dict):
            raise KeywordReviewInputError("Each keyword must be an object.")
        extra_keys = set(item) - {"keyword_name"}
        if extra_keys:
            raise KeywordReviewInputError(
                f"Keyword contains unsupported fields: {', '.join(sorted(extra_keys))}."
            )
        raw_keyword = item.get("keyword_name")
        if not isinstance(raw_keyword, str) or not raw_keyword.strip():
            raise KeywordReviewInputError("keyword_name must not be empty.")

        keyword = raw_keyword.strip()
        key = normalize_for_compare(keyword)
        if not key:
            raise KeywordReviewInputError("keyword_name must not be empty.")
        if key in seen:
            raise KeywordReviewInputError(
                f"Duplicate keyword_name in same chunk: {keyword}"
            )
        seen.add(key)
        keywords.append({"keyword_name": keyword})

    return keywords


def _normalize_keywords(raw_keywords: Any) -> list[dict[str, str]]:
    keywords, _debug = _normalize_keywords_with_debug(raw_keywords)
    return keywords


def _normalize_keywords_with_debug(raw_keywords: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not isinstance(raw_keywords, list):
        return [], {
            "raw_count": 0,
            "removed": [
                {
                    "keyword": f"<{type(raw_keywords).__name__}>",
                    "reason": "invalid shape",
                }
            ],
        }

    keywords: list[dict[str, str]] = []
    seen: set[str] = set()
    removed: list[dict[str, str]] = []
    for item in raw_keywords:
        keyword: str | None = None

        if isinstance(item, dict):
            raw_keyword = item.get("keyword_name") or item.get("keyword")
            if isinstance(raw_keyword, str):
                keyword = raw_keyword.strip()
            else:
                removed.append({"keyword": repr(item), "reason": "invalid shape"})
                continue
        elif isinstance(item, str):
            keyword = item.strip()
        else:
            removed.append({"keyword": repr(item), "reason": "invalid shape"})
            continue

        if not keyword:
            removed.append({"keyword": repr(item), "reason": "empty"})
            continue

        key = _keyword_exact_key(keyword)
        if not key:
            removed.append({"keyword": keyword, "reason": "empty"})
            continue
        if key in seen:
            removed.append({"keyword": keyword, "reason": "duplicate"})
            continue

        seen.add(key)
        keywords.append({"keyword_name": keyword})

    return keywords, {
        "raw_count": len(raw_keywords),
        "removed": removed,
    }


def _merge_keywords(
    existing_keywords: list[dict[str, str]],
    new_keywords: list[dict[str, str]],
    target_count: int,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in [*existing_keywords, *new_keywords]:
        keyword = item.get("keyword_name", "").strip()
        key = _keyword_exact_key(keyword)
        if not keyword or not key or key in seen:
            continue
        seen.add(key)
        merged.append({"keyword_name": keyword})
        if len(merged) >= target_count:
            break

    return merged


def _keyword_exact_key(keyword: str) -> str:
    return " ".join(keyword.strip().casefold().split())


def _log_keyword_normalization_debug(
    *,
    chunk_name: str,
    stage: str,
    attempt: int,
    retry_attempt: int,
    raw_count: int,
    normalized_count: int,
    removed: list[dict[str, str]],
) -> None:
    reason_counts: dict[str, int] = {
        "empty": 0,
        "duplicate": 0,
        "invalid shape": 0,
        "too long": 0,
    }
    for item in removed:
        reason = item.get("reason", "invalid shape")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    logger.info(
        "Keyword extraction normalization: chunk=%s stage=%s attempt=%s retry_attempt=%s raw_count=%s normalized_count=%s removed_counts=%s removed=%s",
        chunk_name,
        stage,
        attempt,
        retry_attempt,
        raw_count,
        normalized_count,
        reason_counts,
        removed,
    )


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


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if value is None or isinstance(value, bool):
        raise KeywordReviewInputError(f"Required integer field is missing: {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise KeywordReviewInputError(f"Required integer field is invalid: {field}") from exc


__all__ = [
    "KeywordExtractionCountError",
    "KeywordDebugInputError",
    "KeywordReviewInputError",
    "approve_keywords_for_lesson",
    "extract_keywords_for_lesson_debug",
    "extract_keyword_for_chunk",
    "get_keywords_for_lesson",
    "normalize_keyword_payload",
    "update_keywords_for_lesson",
]
