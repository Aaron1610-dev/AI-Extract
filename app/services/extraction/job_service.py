from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import UploadFile

from app.schemas.extraction import ExtractionJobResponse, ExtractionJobStatus
from app.services.storage.workspace_service import (
    create_job_dirs,
    get_job_json_path,
    get_job_output_dir,
    get_original_pdf_path,
    job_exists,
    read_json,
    save_original_pdf,
    write_json,
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_pdf_upload(file: UploadFile | None) -> UploadFile:
    if file is None:
        raise ValueError("PDF file is required.")

    filename = (file.filename or "").strip()
    if not filename:
        raise ValueError("Uploaded file must have a filename.")

    if not filename.lower().endswith(".pdf"):
        raise ValueError("Uploaded file must be a PDF with .pdf extension.")

    return file


def create_job_from_upload(file: UploadFile | None) -> ExtractionJobResponse:
    upload_file = _validate_pdf_upload(file)
    job_id = str(uuid4())

    create_job_dirs(job_id)
    upload_path = save_original_pdf(job_id, upload_file)
    output_dir = get_job_output_dir(job_id)

    now = _utc_now_iso()
    payload = {
        "job_id": job_id,
        "status": ExtractionJobStatus.UPLOADED.value,
        "source_file": upload_file.filename or "original.pdf",
        "upload_path": str(upload_path),
        "output_dir": str(output_dir),
        "created_at": now,
        "updated_at": now,
    }

    write_json(get_job_json_path(job_id), payload)
    return ExtractionJobResponse.model_validate(payload)


def get_job(job_id: str) -> ExtractionJobResponse:
    job_json_path = get_job_json_path(job_id)
    if not job_exists(job_id):
        raise FileNotFoundError(f"Extraction job '{job_id}' was not found.")

    return ExtractionJobResponse.model_validate(read_json(job_json_path))


def update_job_status(
    job_id: str,
    status: ExtractionJobStatus,
) -> ExtractionJobResponse:
    job = get_job(job_id)
    payload = job.model_dump(mode="json")
    payload["status"] = status.value
    payload["updated_at"] = _utc_now_iso()

    original_pdf_path = get_original_pdf_path(job_id)
    if original_pdf_path.exists():
        payload["upload_path"] = str(original_pdf_path)

    write_json(get_job_json_path(job_id), payload)
    return ExtractionJobResponse.model_validate(payload)
