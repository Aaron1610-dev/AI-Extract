from __future__ import annotations

from app.schemas.extraction import (
    ExtractionJobStatus,
    TopicApproveResponse,
    TopicExtractionResponse,
    TopicItem,
    TopicReviewResponse,
)
from app.pipeline.gemini_extract.topic_runner import run_topic_extraction
from app.services.extraction.job_service import get_job, update_job_status
from app.services.storage.workspace_service import (
    get_job_output_dir,
    get_lesson_raw_json_path,
    get_original_pdf_path,
    get_topic_raw_json_path,
    get_topics_approved_json_path,
    get_topics_json_path,
    read_json,
    write_json,
)


def _topic_items_from_payload(payload: list[dict]) -> list[TopicItem]:
    return [TopicItem.model_validate(item) for item in payload]


def _read_topics_or_404(job_id: str) -> list[TopicItem]:
    topics_path = get_topics_json_path(job_id)
    if not topics_path.exists():
        raise FileNotFoundError("Topics have not been extracted for this job yet.")

    topics = read_json(topics_path)
    if not isinstance(topics, list):
        raise ValueError(f"Expected topics list in {topics_path}")

    return _topic_items_from_payload(topics)


def extract_topics(
    job_id: str,
    offset: str | int | None = "auto",
    split_pdf: bool = True,
    model: str | None = None,
) -> TopicExtractionResponse:
    get_job(job_id)

    original_pdf_path = get_original_pdf_path(job_id)
    if not original_pdf_path.exists():
        raise FileNotFoundError(f"Original PDF for job '{job_id}' was not found.")

    update_job_status(job_id, ExtractionJobStatus.EXTRACTING_TOPICS)

    topic_raw_path = get_topic_raw_json_path(job_id)
    topics_path = get_topics_json_path(job_id)
    lesson_raw_path = get_lesson_raw_json_path(job_id)
    output_root = get_job_output_dir(job_id)

    try:
        result = run_topic_extraction(
            pdf_path=original_pdf_path,
            model=model,
            offset=offset,
            split_pdf=split_pdf,
            output_root=output_root,
        )
    except Exception:
        update_job_status(job_id, ExtractionJobStatus.ERROR)
        raise

    topics = result.get("topics")
    lessons = result.get("lessons")

    if not isinstance(topics, list):
        update_job_status(job_id, ExtractionJobStatus.ERROR)
        raise ValueError("Topic extraction did not return a topics list.")

    if not isinstance(lessons, list):
        update_job_status(job_id, ExtractionJobStatus.ERROR)
        raise ValueError("Topic extraction did not return a lessons list.")

    try:
        topic_items = _topic_items_from_payload(topics)
    except Exception:
        update_job_status(job_id, ExtractionJobStatus.ERROR)
        raise

    raw_payload = {
        "job_id": job_id,
        "source": "gemini",
        "total_pdf_pages": result.get("total_pdf_pages"),
        "extraction_input": result.get("extraction_input"),
        "front_matter_pdf_path": result.get("front_matter_pdf_path"),
        "fallback_used": result.get("fallback_used"),
        "offset": result.get("offset"),
        "offset_detection": result.get("offset_detection"),
        "topics": topics,
        "lessons": lessons,
        "raw_response_text": result.get("raw_response_text"),
        "raw_payload": result.get("raw_payload"),
        "split_result": result.get("split_result"),
    }

    write_json(topic_raw_path, raw_payload)
    write_json(topics_path, topics)
    write_json(lesson_raw_path, lessons)

    job = update_job_status(job_id, ExtractionJobStatus.REVIEWING_TOPICS)

    return TopicExtractionResponse(
        job_id=job_id,
        offset=result.get("offset"),
        status=job.status.value,
        topics=topic_items,
    )


def get_topics(job_id: str) -> TopicReviewResponse:
    job = get_job(job_id)
    topics_path = get_topics_json_path(job_id)
    topics = _read_topics_or_404(job_id)

    return TopicReviewResponse(
        job_id=job_id,
        status=job.status,
        topics=topics,
        topics_path=str(topics_path),
    )


def update_topics(job_id: str, topics: list[TopicItem]) -> TopicReviewResponse:
    job = get_job(job_id)
    topics_path = get_topics_json_path(job_id)
    if not topics_path.exists():
        raise FileNotFoundError("Topics have not been extracted for this job yet.")

    write_json(topics_path, [topic.model_dump(mode="json") for topic in topics])

    if job.status != ExtractionJobStatus.TOPICS_APPROVED:
        job = update_job_status(job_id, ExtractionJobStatus.REVIEWING_TOPICS)

    return TopicReviewResponse(
        job_id=job_id,
        status=job.status,
        topics=topics,
        topics_path=str(topics_path),
    )


def approve_topics(job_id: str) -> TopicApproveResponse:
    get_job(job_id)
    topics = _read_topics_or_404(job_id)
    topics_approved_path = get_topics_approved_json_path(job_id)

    write_json(
        topics_approved_path,
        [topic.model_dump(mode="json") for topic in topics],
    )

    job = update_job_status(job_id, ExtractionJobStatus.TOPICS_APPROVED)

    return TopicApproveResponse(
        job_id=job_id,
        status=job.status,
        topics=topics,
        topics_approved_path=str(topics_approved_path),
    )
