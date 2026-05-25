from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app.schemas.extraction import (
    LessonApproveResponse,
    LessonExtractionResponse,
    LessonListRequest,
    LessonReviewResponse,
)
from app.services.extraction.lesson_service import (
    LessonPrerequisiteError,
    LessonsAlreadyApprovedError,
    approve_lessons,
    build_lessons_from_approved_topics,
    get_lessons,
    update_lessons,
)


router = APIRouter(prefix="/api/extract/jobs", tags=["extract-lessons"])


@router.post("/{job_id}/lessons/build", response_model=LessonExtractionResponse)
def build_job_lessons(job_id: str) -> LessonExtractionResponse:
    try:
        return build_lessons_from_approved_topics(job_id)

    except LessonPrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build lessons: {exc}",
        ) from exc


@router.get("/{job_id}/lessons", response_model=LessonReviewResponse)
def get_job_lessons(job_id: str) -> LessonReviewResponse:
    try:
        return get_lessons(job_id)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read lessons: {exc}",
        ) from exc


@router.put("/{job_id}/lessons", response_model=LessonReviewResponse)
def update_job_lessons(
    job_id: str,
    payload: dict = Body(...),
) -> LessonReviewResponse:
    try:
        request = LessonListRequest.model_validate(payload)
        return update_lessons(job_id, request.lessons)

    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except LessonsAlreadyApprovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update lessons: {exc}",
        ) from exc


@router.post("/{job_id}/lessons/approve", response_model=LessonApproveResponse)
def approve_job_lessons(job_id: str) -> LessonApproveResponse:
    try:
        return approve_lessons(job_id)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve lessons: {exc}",
        ) from exc
