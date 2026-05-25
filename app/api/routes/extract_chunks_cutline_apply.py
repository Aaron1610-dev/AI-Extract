from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.extraction import ChunkCutlineApplyResponse
from app.services.extraction.chunk_cutline_apply_service import (
    ChunkCutlineApplyInputError,
    apply_cutline_for_chunk,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/chunks/debug",
    tags=["extract-chunks-cutline-apply"],
)


@router.post(
    "/lesson/{lesson_name}/chunk/{chunk_name}/cutline/apply",
    response_model=ChunkCutlineApplyResponse,
)
def apply_cutline_for_job_lesson_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> ChunkCutlineApplyResponse:
    try:
        return apply_cutline_for_chunk(
            job_id=job_id,
            lesson_name=lesson_name,
            chunk_name=chunk_name,
        )

    except ChunkCutlineApplyInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply chunk cutline: {exc}",
        ) from exc
