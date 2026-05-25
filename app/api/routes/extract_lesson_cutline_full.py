from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.extraction import LessonCutlineFullResponse
from app.services.extraction.chunk_cutline_debug_service import (
    ChunkCutlineInputError,
    KaggleCutlineDebugNotConfigured,
)
from app.services.extraction.lesson_cutline_full_service import (
    LessonCutlineFullInputError,
    process_full_lesson_cutlines,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/chunks/debug",
    tags=["extract-lesson-cutline-full"],
)


@router.post(
    "/lesson/{lesson_name}/cutline/full",
    response_model=LessonCutlineFullResponse,
)
def process_full_lesson_cutline(
    job_id: str,
    lesson_name: str,
) -> LessonCutlineFullResponse:
    try:
        return process_full_lesson_cutlines(
            job_id=job_id,
            lesson_name=lesson_name,
        )

    except (ChunkCutlineInputError, LessonCutlineFullInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except KaggleCutlineDebugNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process full lesson cutlines: {exc}",
        ) from exc
