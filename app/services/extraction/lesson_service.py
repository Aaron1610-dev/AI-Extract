from __future__ import annotations

import re

from app.schemas.extraction import (
    ExtractionJobStatus,
    LessonApproveResponse,
    LessonExtractionResponse,
    LessonItem,
    LessonReviewResponse,
    TopicItem,
)
from app.services.extraction.job_service import get_job, update_job_status
from app.services.storage.workspace_service import (
    get_lessons_approved_json_path,
    get_lessons_json_path,
    get_lesson_raw_json_path,
    get_original_pdf_path,
    get_topics_approved_json_path,
    read_json,
    write_json,
)


class LessonPrerequisiteError(RuntimeError):
    pass


class LessonsAlreadyApprovedError(RuntimeError):
    pass


_LESSON_HEADING_RE = re.compile(r"^\s*Bài\s+\d+", re.IGNORECASE)


def is_valid_review_lesson(item: dict) -> bool:
    heading = item.get("heading")
    if not isinstance(heading, str):
        return False

    return _LESSON_HEADING_RE.match(heading.strip()) is not None


def _read_topics_approved_or_409(job_id: str) -> list[TopicItem]:
    topics_path = get_topics_approved_json_path(job_id)
    if not topics_path.exists():
        raise LessonPrerequisiteError("Topics must be approved before building lessons.")

    topics = read_json(topics_path)
    if not isinstance(topics, list):
        raise ValueError(f"Expected topics list in {topics_path}")

    return [TopicItem.model_validate(item) for item in topics]


def _read_raw_lessons_or_409(job_id: str) -> list[dict]:
    raw_lessons_path = get_lesson_raw_json_path(job_id)
    if not raw_lessons_path.exists():
        raise LessonPrerequisiteError("Raw lessons are missing. Run topic extraction first.")

    raw_lessons = read_json(raw_lessons_path)
    if not isinstance(raw_lessons, list):
        raise ValueError(f"Expected raw_lessons list in {raw_lessons_path}")

    return [item for item in raw_lessons if isinstance(item, dict)]


def _read_lessons_or_404(job_id: str) -> list[LessonItem]:
    lessons_path = get_lessons_json_path(job_id)
    if not lessons_path.exists():
        raise FileNotFoundError("Lessons have not been extracted for this job yet.")

    lessons = read_json(lessons_path)
    if not isinstance(lessons, list):
        raise ValueError(f"Expected lessons list in {lessons_path}")

    return [LessonItem.model_validate(item) for item in lessons]


def _build_lessons_from_ranges(
    approved_topics: list[TopicItem],
    raw_lessons: list[dict],
) -> list[LessonItem]:
    lessons: list[LessonItem] = []
    seen_raw_keys: set[tuple] = set()
    reviewable_raw_lessons = [
        raw_lesson
        for raw_lesson in raw_lessons
        if is_valid_review_lesson(raw_lesson)
    ]

    for topic in approved_topics:
        topic_lessons: list[LessonItem] = []

        for raw_lesson in reviewable_raw_lessons:
            lesson_start = int(raw_lesson.get("start") or 0)
            lesson_end = int(raw_lesson.get("end") or 0)
            raw_key = (
                raw_lesson.get("name"),
                lesson_start,
                lesson_end,
            )

            if raw_key in seen_raw_keys:
                continue

            if lesson_end >= topic.start and lesson_start <= topic.end:
                seen_raw_keys.add(raw_key)
                topic_lessons.append(
                    LessonItem(
                        name=str(raw_lesson.get("name") or f"lesson_{len(lessons) + len(topic_lessons) + 1:02d}"),
                        start=max(lesson_start, topic.start),
                        end=min(lesson_end, topic.end),
                        heading=raw_lesson.get("heading"),
                        title=str(raw_lesson.get("title") or topic.title),
                        topic_name=topic.name,
                        topic_title=topic.title,
                    )
                )

        lessons.extend(topic_lessons)

    return _renumber_lessons(lessons)


def _renumber_lessons(lessons: list[LessonItem]) -> list[LessonItem]:
    sorted_lessons = sorted(lessons, key=lambda lesson: (lesson.start, lesson.end))
    return [
        lesson.model_copy(update={"name": f"lesson_{index:02d}"})
        for index, lesson in enumerate(sorted_lessons, start=1)
    ]


def build_lessons_from_approved_topics(job_id: str) -> LessonExtractionResponse:
    get_job(job_id)

    original_pdf_path = get_original_pdf_path(job_id)
    if not original_pdf_path.exists():
        raise FileNotFoundError(f"Original PDF for job '{job_id}' was not found.")

    approved_topics = _read_topics_approved_or_409(job_id)
    raw_lessons = _read_raw_lessons_or_409(job_id)

    update_job_status(job_id, ExtractionJobStatus.EXTRACTING_LESSONS)

    lessons = _build_lessons_from_ranges(approved_topics, raw_lessons)
    lessons_payload = [lesson.model_dump(mode="json") for lesson in lessons]

    lessons_path = get_lessons_json_path(job_id)
    write_json(lessons_path, lessons_payload)

    job = update_job_status(job_id, ExtractionJobStatus.REVIEWING_LESSONS)

    return LessonExtractionResponse(
        job_id=job_id,
        status=job.status,
        lessons=lessons,
        lessons_path=str(lessons_path),
    )


def get_lessons(job_id: str) -> LessonReviewResponse:
    job = get_job(job_id)
    lessons_path = get_lessons_json_path(job_id)
    lessons = _read_lessons_or_404(job_id)

    return LessonReviewResponse(
        job_id=job_id,
        status=job.status,
        lessons=lessons,
        lessons_path=str(lessons_path),
    )


def update_lessons(job_id: str, lessons: list[LessonItem]) -> LessonReviewResponse:
    job = get_job(job_id)
    if job.status == ExtractionJobStatus.LESSONS_APPROVED:
        raise LessonsAlreadyApprovedError(
            "Lessons are already approved. Re-open lesson review is not implemented yet."
        )

    lessons_path = get_lessons_json_path(job_id)
    if not lessons_path.exists():
        raise FileNotFoundError("Lessons have not been extracted for this job yet.")

    write_json(lessons_path, [lesson.model_dump(mode="json") for lesson in lessons])

    job = update_job_status(job_id, ExtractionJobStatus.REVIEWING_LESSONS)

    return LessonReviewResponse(
        job_id=job_id,
        status=job.status,
        lessons=lessons,
        lessons_path=str(lessons_path),
    )


def approve_lessons(job_id: str) -> LessonApproveResponse:
    get_job(job_id)
    lessons = _read_lessons_or_404(job_id)
    lessons_approved_path = get_lessons_approved_json_path(job_id)

    write_json(
        lessons_approved_path,
        [lesson.model_dump(mode="json") for lesson in lessons],
    )

    job = update_job_status(job_id, ExtractionJobStatus.LESSONS_APPROVED)

    return LessonApproveResponse(
        job_id=job_id,
        status=job.status,
        lessons=lessons,
        lessons_approved_path=str(lessons_approved_path),
    )
