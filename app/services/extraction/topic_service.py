from __future__ import annotations

from app.schemas.extraction import (
    ExtractionJobStatus,
    TopicApproveResponse,
    TopicExtractionResponse,
    TopicItem,
    TopicReviewResponse,
)
from app.services.extraction.job_service import get_job, update_job_status
from app.services.storage.workspace_service import (
    get_lesson_raw_json_path,
    get_original_pdf_path,
    get_topic_raw_json_path,
    get_topics_approved_json_path,
    get_topics_json_path,
    read_json,
    write_json,
)


_STUB_TOPICS = [
    {
        "name": "topic_01",
        "start": 1,
        "end": 5,
        "heading": "CHỦ ĐỀ 1.",
        "title": "CHỦ ĐỀ MẪU",
    }
]

_STUB_RAW_LESSONS = [
    {
        "name": "lesson_01",
        "start": 1,
        "end": 3,
        "heading": "Bài 1.",
        "title": "BÀI HỌC MẪU 1",
    },
    {
        "name": "lesson_02",
        "start": 4,
        "end": 5,
        "heading": "Bài 2.",
        "title": "BÀI HỌC MẪU 2",
    },
]


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


def extract_topics_stub(job_id: str) -> TopicExtractionResponse:
    get_job(job_id)

    original_pdf_path = get_original_pdf_path(job_id)
    if not original_pdf_path.exists():
        raise FileNotFoundError(f"Original PDF for job '{job_id}' was not found.")

    update_job_status(job_id, ExtractionJobStatus.EXTRACTING_TOPICS)

    topic_raw_path = get_topic_raw_json_path(job_id)
    topics_path = get_topics_json_path(job_id)
    lesson_raw_path = get_lesson_raw_json_path(job_id)

    raw_payload = {
        "job_id": job_id,
        "source": "stub",
        "topics": _STUB_TOPICS,
        "lessons": _STUB_RAW_LESSONS,
    }

    write_json(topic_raw_path, raw_payload)
    write_json(topics_path, _STUB_TOPICS)
    write_json(lesson_raw_path, _STUB_RAW_LESSONS)

    job = update_job_status(job_id, ExtractionJobStatus.REVIEWING_TOPICS)

    return TopicExtractionResponse(
        job_id=job_id,
        status=job.status,
        topics=_topic_items_from_payload(_STUB_TOPICS),
        topics_path=str(topics_path),
        topic_raw_path=str(topic_raw_path),
        lesson_raw_path=str(lesson_raw_path),
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
