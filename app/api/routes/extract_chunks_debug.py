from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.extraction import ChunkDebugResponse
from app.services.extraction.chunk_debug_service import (
    ChunkDebugPrerequisiteError,
    extract_debug_chunks_for_lesson,
)


router = APIRouter(
    prefix="/api/extract/jobs/{job_id}/chunks/debug",
    tags=["extract-chunks-debug"],
)


@router.post("/lesson/{lesson_name}", response_model=ChunkDebugResponse)
def extract_debug_chunks_for_job_lesson(
    job_id: str,
    lesson_name: str,
) -> ChunkDebugResponse:
    try:
        return extract_debug_chunks_for_lesson(
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
            detail=f"Failed to extract debug chunks: {exc}",
        ) from exc
