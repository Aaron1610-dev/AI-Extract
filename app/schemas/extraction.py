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
    status: str
    offset: int | None = None
    topics: list[TopicItem]


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


class ChunkItem(BaseModel):
    name: str
    start: int
    end: int
    first_chunk: bool | None = None
    content_head: bool | None = None
    heading: str | None = None
    title: str


class ChunkDebugResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunks: list[ChunkItem]


class ChunkCutlineDebugResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunk_name: str
    matched: bool
    page_number: int
    heading: str
    title: str
    matched_text: str | None = None
    bbox: list[int] | None = None
    y_cut: int | None = None
    match_score: int | None = None
    matched_prefix: int | None = None
    expected_len: int | None = None
    match_ratio: float | None = None
    best_mode: str | None = None
    weak_cut: bool | None = None
    force_cut: bool | None = None
    early_stop: bool | None = None
    reason: str | None = None
    debug_json_path: str
    debug_page_path: str | None = None
    debug_bbox_path: str | None = None
    promoted: bool = False
    promote_status: str = "not_run"
    promote_reason: str | None = None
    previous_chunk: str | None = None
    selected_chunk_pdf: str | None = None
    previous_chunk_pdf: str | None = None
    debug_promote_json_path: str | None = None


class LessonCutlineFullResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    processed_chunks: list[str]
    skipped_chunks: list[dict[str, str]]
    failed_chunks: list[dict[str, str]]
    updated_pdfs: list[str]
    debug_summary_path: str


class KeywordItem(BaseModel):
    keyword_name: str


class LessonKeywordDebugResult(BaseModel):
    chunk_name: str
    keyword_count: int
    keywords: list[KeywordItem]
    keyword_path: str


class LessonKeywordDebugResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunk_count: int
    results: list[LessonKeywordDebugResult]
