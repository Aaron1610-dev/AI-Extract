from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app.schemas.extraction import (
    LessonKeywordApproveResponse,
    LessonKeywordListRequest,
    LessonKeywordReviewResponse,
)
from app.services.extraction.keyword_debug_service import (
    KeywordReviewInputError,
    approve_keywords_for_lesson,
    get_keywords_for_lesson,
    update_keywords_for_lesson,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/keywords",
    tags=["extract-keywords"],
)


@router.get(
    "/lesson/{lesson_name}",
    response_model=LessonKeywordReviewResponse,
    response_model_exclude_none=True,
)
def get_job_lesson_keywords(
    job_id: str,
    lesson_name: str,
) -> LessonKeywordReviewResponse:
    try:
        return get_keywords_for_lesson(job_id=job_id, lesson_name=lesson_name)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read lesson keywords: {exc}",
        ) from exc


@router.put(
    "/lesson/{lesson_name}",
    response_model=LessonKeywordReviewResponse,
    response_model_exclude_none=True,
)
def update_job_lesson_keywords(
    job_id: str,
    lesson_name: str,
    payload: dict = Body(...),
) -> LessonKeywordReviewResponse:
    try:
        request = LessonKeywordListRequest.model_validate(payload)
        return update_keywords_for_lesson(
            job_id=job_id,
            lesson_name=lesson_name,
            results=request.results,
        )

    except (ValidationError, KeywordReviewInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update lesson keywords: {exc}",
        ) from exc


@router.post(
    "/lesson/{lesson_name}/approve",
    response_model=LessonKeywordApproveResponse,
    response_model_exclude_none=True,
)
def approve_job_lesson_keywords(
    job_id: str,
    lesson_name: str,
) -> LessonKeywordApproveResponse:
    try:
        return approve_keywords_for_lesson(job_id=job_id, lesson_name=lesson_name)

    except KeywordReviewInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve lesson keywords: {exc}",
        ) from exc
