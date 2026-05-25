from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.extraction import ExtractionJobResponse
from app.services.extraction.job_service import create_job_from_upload, get_job


router = APIRouter(prefix="/api/extract/jobs", tags=["extract-jobs"])


@router.post("", response_model=ExtractionJobResponse)
def create_extraction_job(
    file: UploadFile | None = File(default=None),
) -> ExtractionJobResponse:
    try:
        return create_job_from_upload(file)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create extraction job: {exc}",
        ) from exc


@router.get("/{job_id}", response_model=ExtractionJobResponse)
def get_extraction_job(job_id: str) -> ExtractionJobResponse:
    try:
        return get_job(job_id)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read extraction job: {exc}",
        ) from exc
