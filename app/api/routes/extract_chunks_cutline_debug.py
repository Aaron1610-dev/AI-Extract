from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.extraction import ChunkCutlineDebugResponse
from app.services.extraction.chunk_cutline_debug_service import (
    ChunkCutlineInputError,
    KaggleCutlineDebugNotConfigured,
    detect_debug_cutline_for_chunk,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/chunks/debug",
    tags=["extract-chunks-cutline-debug"],
)


@router.post(
    "/lesson/{lesson_name}/chunk/{chunk_name}/cutline",
    response_model=ChunkCutlineDebugResponse,
    response_model_exclude_none=True,
)
def detect_cutline_for_job_lesson_chunk(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> ChunkCutlineDebugResponse:
    try:
        return detect_debug_cutline_for_chunk(
            job_id=job_id,
            lesson_name=lesson_name,
            chunk_name=chunk_name,
        )

    except ChunkCutlineInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except KaggleCutlineDebugNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to detect chunk cutline: {exc}",
        ) from exc
