from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(extra="forbid")

    name: str
    start: int
    end: int
    first_chunk: bool | None = None
    content_head: bool | None = None
    heading: str | None = None
    title: str


class ChunkListRequest(BaseModel):
    chunks: list[ChunkItem]


class ChunkDebugResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunks: list[ChunkItem]


class ChunkReviewResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    chunks: list[ChunkItem]


class ChunkApproveResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    chunks: list[ChunkItem]
    chunks_approved_path: str


class KeywordItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword_name: str


class LessonKeywordDebugResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_name: str
    keyword_count: int
    keywords: list[KeywordItem]
    keyword_path: str | None = None


class LessonKeywordEditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_name: str
    keyword_count: int
    keywords: list[KeywordItem]


class LessonKeywordListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[LessonKeywordEditResult]


class LessonKeywordDebugResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunk_count: int
    results: list[LessonKeywordDebugResult]


class LessonKeywordReviewResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    results: list[LessonKeywordDebugResult]
    missing_chunks: list[str] = Field(default_factory=list)


class KeywordChunkExtractResponse(BaseModel):
    job_id: str
    lesson_name: str
    chunk_name: str
    keyword_count: int
    keywords: list[KeywordItem]
    keyword_path: str


class LessonKeywordApproveResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    approved_at: str
    results: list[LessonKeywordDebugResult]
    keywords_approved_path: str


class LessonCutlineFullResponse(BaseModel):
    job_id: str
    lesson_name: str
    status: str
    kaggle_mode: str | None = None
    kaggle_runs: int | None = None
    processed_chunks: list[str]
    skipped_chunks: list[dict[str, str]]
    failed_chunks: list[dict[str, str]]
    updated_pdfs: list[str]
    debug_summary_path: str
