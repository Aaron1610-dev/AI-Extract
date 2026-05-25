"""PDF utilities for future Topic/Lesson extraction."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def count_pdf_pages(source_pdf: str | Path) -> int:
    path = _validate_pdf_path(source_pdf)
    reader = PdfReader(str(path))
    return len(reader.pages)


def printed_to_pdf_page(printed_page: int, offset: int) -> int:
    return int(printed_page) + int(offset)


def clamp_page_range(start: int, end: int, total_pages: int) -> tuple[int, int]:
    if total_pages < 1:
        raise ValueError("total_pages must be greater than 0")

    start = max(1, min(int(start), total_pages))
    end = max(1, min(int(end), total_pages))

    if end < start:
        end = start

    return start, end


def split_pdf_range(
    source_pdf: str | Path,
    output_pdf: str | Path,
    start_page: int,
    end_page: int,
) -> Path:
    source_path = _validate_pdf_path(source_pdf)
    output_path = Path(output_pdf)

    reader = PdfReader(str(source_path))
    total_pages = len(reader.pages)

    if start_page < 1 or end_page < 1:
        raise ValueError("PDF page range must use 1-based positive page numbers")

    if end_page < start_page:
        raise ValueError("end_page must be greater than or equal to start_page")

    if start_page > total_pages:
        raise ValueError(
            f"start_page={start_page} is outside PDF page count {total_pages}"
        )

    start_page, end_page = clamp_page_range(start_page, end_page, total_pages)

    writer = PdfWriter()

    for page_index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[page_index])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("wb") as file_obj:
        writer.write(file_obj)

    return output_path


def create_front_matter_pdf(
    source_pdf: str | Path,
    output_pdf: str | Path,
    start_page: int = 1,
    end_page: int = 12,
) -> Path:
    return split_pdf_range(
        source_pdf=source_pdf,
        output_pdf=output_pdf,
        start_page=start_page,
        end_page=end_page,
    )


def split_topics_and_lessons(
    source_pdf: str | Path,
    output_root: str | Path,
    topics: list[dict],
    lessons: list[dict],
    book_stem: str = "book",
) -> dict:
    del book_stem

    root = Path(output_root)
    topic_doc_dir = root / "topic" / "doc"
    lesson_doc_dir = root / "lesson" / "doc"

    topic_doc_dir.mkdir(parents=True, exist_ok=True)
    lesson_doc_dir.mkdir(parents=True, exist_ok=True)

    topic_docs = [
        _split_named_item(source_pdf, topic_doc_dir, item)
        for item in topics
    ]
    lesson_docs = [
        _split_named_item(source_pdf, lesson_doc_dir, item)
        for item in lessons
    ]

    return {
        "topic_docs": topic_docs,
        "lesson_docs": lesson_docs,
    }


def _validate_pdf_path(source_pdf: str | Path) -> Path:
    path = Path(source_pdf)

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF file must have a .pdf extension: {path}")

    return path


def _split_named_item(
    source_pdf: str | Path,
    output_dir: Path,
    item: dict,
) -> dict:
    name = str(item.get("name") or "").strip()

    if not name:
        raise ValueError("Split item is missing name")

    start = item.get("start")
    end = item.get("end")

    if start is None or end is None:
        raise ValueError(f"Split item {name} must include start and end")

    pdf_path = output_dir / f"{name}.pdf"

    split_pdf_range(
        source_pdf=source_pdf,
        output_pdf=pdf_path,
        start_page=int(start),
        end_page=int(end),
    )

    return {
        "name": name,
        "pdf_path": str(pdf_path),
    }
