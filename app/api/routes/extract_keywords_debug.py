from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.extraction import LessonKeywordDebugResponse
from app.services.extraction.keyword_debug_service import (
    KeywordDebugInputError,
    extract_keywords_for_lesson_debug,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/keywords/debug",
    tags=["extract-keywords-debug"],
)


@router.post(
    "/lesson/{lesson_name}/extract",
    response_model=LessonKeywordDebugResponse,
)
def extract_keywords_for_job_lesson(
    job_id: str,
    lesson_name: str,
) -> LessonKeywordDebugResponse:
    try:
        return extract_keywords_for_lesson_debug(
            job_id=job_id,
            lesson_name=lesson_name,
        )

    except KeywordDebugInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract lesson keywords: {exc}",
        ) from exc
