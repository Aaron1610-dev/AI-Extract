from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app.schemas.extraction import (
    ChunkApproveResponse,
    ChunkListRequest,
    ChunkReviewResponse,
    LessonCutlineFullResponse,
)
from app.services.extraction.chunk_cutline_debug_service import (
    ChunkCutlineInputError,
    KaggleCutlineNotConfigured,
)
from app.services.extraction.chunk_debug_service import (
    ChunkDebugPrerequisiteError,
    ChunkReviewInputError,
    approve_chunks_for_lesson,
    extract_chunks_for_lesson,
    get_chunks_for_lesson,
    update_chunks_for_lesson,
)
from app.services.extraction.lesson_cutline_full_service import (
    LessonCutlineFullInputError,
    process_full_lesson_cutlines,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/chunks",
    tags=["extract-chunks"],
)


@router.post(
    "/lesson/{lesson_name}/extract",
    response_model=ChunkReviewResponse,
    response_model_exclude_none=True,
)
def extract_chunks_for_job_lesson(
    job_id: str,
    lesson_name: str,
) -> ChunkReviewResponse:
    try:
        return extract_chunks_for_lesson(
            job_id=job_id,
            lesson_name=lesson_name,
        )

    except ChunkDebugPrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract chunks: {exc}",
        ) from exc


@router.get(
    "/lesson/{lesson_name}",
    response_model=ChunkReviewResponse,
    response_model_exclude_none=True,
)
def get_job_lesson_chunks(
    job_id: str,
    lesson_name: str,
) -> ChunkReviewResponse:
    try:
        return get_chunks_for_lesson(job_id=job_id, lesson_name=lesson_name)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read chunks: {exc}",
        ) from exc


@router.put(
    "/lesson/{lesson_name}",
    response_model=ChunkReviewResponse,
    response_model_exclude_none=True,
)
def update_job_lesson_chunks(
    job_id: str,
    lesson_name: str,
    payload: dict = Body(...),
) -> ChunkReviewResponse:
    try:
        request = ChunkListRequest.model_validate(payload)
        return update_chunks_for_lesson(
            job_id=job_id,
            lesson_name=lesson_name,
            chunks=request.chunks,
        )

    except (ValidationError, ChunkReviewInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update chunks: {exc}",
        ) from exc


@router.post(
    "/lesson/{lesson_name}/approve",
    response_model=ChunkApproveResponse,
    response_model_exclude_none=True,
)
def approve_job_lesson_chunks(
    job_id: str,
    lesson_name: str,
) -> ChunkApproveResponse:
    try:
        return approve_chunks_for_lesson(job_id=job_id, lesson_name=lesson_name)

    except ChunkReviewInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve chunks: {exc}",
        ) from exc


@router.post(
    "/lesson/{lesson_name}/finalize",
    response_model=LessonCutlineFullResponse,
)
def finalize_job_lesson_chunks(
    job_id: str,
    lesson_name: str,
) -> LessonCutlineFullResponse:
    try:
        return process_full_lesson_cutlines(job_id=job_id, lesson_name=lesson_name)

    except (ChunkCutlineInputError, LessonCutlineFullInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except KaggleCutlineNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to finalize lesson chunks: {exc}",
        ) from exc
