from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ExtractionJobStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING_TOPICS = "extracting_topics"
    REVIEWING_TOPICS = "reviewing_topics"
    TOPICS_APPROVED = "topics_approved"
    EXTRACTING_LESSONS = "extracting_lessons"
    REVIEWING_LESSONS = "reviewing_lessons"
    LESSONS_APPROVED = "lessons_approved"
    ERROR = "error"


class ExtractionJobResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    source_file: str
    upload_path: str
    output_dir: str
    created_at: str
    updated_at: str


class TopicItem(BaseModel):
    name: str
    start: int
    end: int
    heading: str | None = None
    title: str


class TopicListRequest(BaseModel):
    topics: list[TopicItem]


class TopicExtractionResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    topics: list[TopicItem]
    topics_path: str
    source: str | None = None
    total_pdf_pages: int | None = None
    extraction_input: str | None = None
    front_matter_pdf_path: str | None = None
    fallback_used: bool | None = None
    offset: int | None = None
    offset_detection: dict | None = None
    topic_raw_path: str | None = None
    lesson_raw_path: str | None = None
    split_result: dict | None = None


class TopicReviewResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    topics: list[TopicItem]
    topics_path: str


class TopicApproveResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    topics: list[TopicItem]
    topics_approved_path: str


class LessonItem(BaseModel):
    name: str
    start: int
    end: int
    heading: str | None = None
    title: str
    topic_name: str | None = None
    topic_title: str | None = None


class LessonListRequest(BaseModel):
    lessons: list[LessonItem]


class LessonExtractionResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    lessons: list[LessonItem]
    lessons_path: str


class LessonReviewResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    lessons: list[LessonItem]
    lessons_path: str


class LessonApproveResponse(BaseModel):
    job_id: str
    status: ExtractionJobStatus
    lessons: list[LessonItem]
    lessons_approved_path: str
