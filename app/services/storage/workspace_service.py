from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.paths import OUTPUTS_DIR, UPLOADS_DIR, WORKSPACE_DIR


def ensure_workspace() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def get_job_upload_dir(job_id: str) -> Path:
    return UPLOADS_DIR / job_id


def get_job_output_dir(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id


def get_original_pdf_path(job_id: str) -> Path:
    return get_job_upload_dir(job_id) / "original.pdf"


def get_job_json_path(job_id: str) -> Path:
    return get_job_output_dir(job_id) / "job.json"


def get_topic_dir(job_id: str) -> Path:
    return get_job_output_dir(job_id) / "topic"


def get_lesson_dir(job_id: str) -> Path:
    return get_job_output_dir(job_id) / "lesson"


def get_chunk_dir(job_id: str) -> Path:
    return get_job_output_dir(job_id) / "chunk"


def get_chunk_lesson_dir(job_id: str, lesson_name: str) -> Path:
    return get_chunk_dir(job_id) / lesson_name


def get_chunk_lesson_doc_dir(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / "doc"


def get_chunk_doc_dir(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_doc_dir(job_id, lesson_name)


def get_chunk_lesson_keyword_dir(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / "keyword"


def get_chunk_debug_dir(job_id: str, lesson_name: str, chunk_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / "debug" / chunk_name


def get_chunk_lesson_debug_dir(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / "debug"


def get_topic_raw_json_path(job_id: str) -> Path:
    return get_topic_dir(job_id) / "topic_raw.json"


def get_topics_json_path(job_id: str) -> Path:
    return get_topic_dir(job_id) / "topics.json"


def get_topics_approved_json_path(job_id: str) -> Path:
    return get_topic_dir(job_id) / "topics_approved.json"


def get_lesson_raw_json_path(job_id: str) -> Path:
    return get_lesson_dir(job_id) / "lesson_raw.json"


def get_lessons_json_path(job_id: str) -> Path:
    return get_lesson_dir(job_id) / "lessons.json"


def get_lessons_approved_json_path(job_id: str) -> Path:
    return get_lesson_dir(job_id) / "lessons_approved.json"


def get_lessons_approved_path(job_id: str) -> Path:
    return get_lessons_approved_json_path(job_id)


def get_lesson_doc_path(job_id: str, lesson_name: str) -> Path:
    return get_lesson_dir(job_id) / "doc" / f"{lesson_name}.pdf"


def get_chunk_json_path(job_id: str, lesson_name: str, chunk_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / f"{chunk_name}.json"


def get_chunks_approved_json_path(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_dir(job_id, lesson_name) / "chunks_approved.json"


def get_chunk_pdf_path(job_id: str, lesson_name: str, chunk_name: str) -> Path:
    return get_chunk_lesson_doc_dir(job_id, lesson_name) / f"{chunk_name}.pdf"


def get_chunk_cutline_json_path(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> Path:
    return get_chunk_debug_dir(job_id, lesson_name, chunk_name) / "cutline.json"


def get_chunk_cutline_page_image_path(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> Path:
    return get_chunk_debug_dir(job_id, lesson_name, chunk_name) / "page.png"


def get_chunk_cutline_bbox_image_path(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> Path:
    return get_chunk_debug_dir(job_id, lesson_name, chunk_name) / "bbox.png"


def get_chunk_cutline_promote_json_path(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> Path:
    return get_chunk_debug_dir(job_id, lesson_name, chunk_name) / "cutline_promote.json"


def get_lesson_cutline_full_json_path(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_debug_dir(job_id, lesson_name) / "lesson_cutline_full.json"


def get_chunk_keyword_path(job_id: str, lesson_name: str, chunk_name: str) -> Path:
    return get_chunk_lesson_keyword_dir(job_id, lesson_name) / f"keyword_{chunk_name}.json"


def get_keywords_approved_json_path(job_id: str, lesson_name: str) -> Path:
    return get_chunk_lesson_keyword_dir(job_id, lesson_name) / "keywords_approved.json"


def get_chunk_cutline_request_dir(
    job_id: str,
    lesson_name: str,
    chunk_name: str,
) -> Path:
    return get_chunk_debug_dir(job_id, lesson_name, chunk_name) / "kaggle"


def create_job_dirs(job_id: str) -> tuple[Path, Path]:
    ensure_workspace()

    upload_dir = get_job_upload_dir(job_id)
    output_dir = get_job_output_dir(job_id)

    upload_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    get_topic_dir(job_id).mkdir(parents=True, exist_ok=False)
    get_lesson_dir(job_id).mkdir(parents=True, exist_ok=False)

    return upload_dir, output_dir


def save_original_pdf(job_id: str, upload_file: UploadFile) -> Path:
    target_path = get_original_pdf_path(job_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    upload_file.file.seek(0)
    with target_path.open("wb") as target:
        shutil.copyfileobj(upload_file.file, target)

    return target_path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def job_exists(job_id: str) -> bool:
    return get_job_json_path(job_id).exists()
