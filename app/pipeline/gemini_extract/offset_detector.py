"""Automatic printed-page to PDF-page offset detection."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.pipeline.gemini_extract.pdf_utils import (
    count_pdf_pages,
    make_single_page_pdf,
)
from app.pipeline.gemini_extract.prompts import build_topic_verify_prompt
from app.pipeline.gemini_extract.topic_parser import parse_json_loose
from app.services.gemini.client import generate_with_pdf


def detect_page_offset(
    source_pdf: str | Path,
    topics: list[dict],
    model: str | None = None,
    candidate_window_before: int = 8,
    candidate_window_after: int = 12,
    min_confidence: float = 0.65,
    temp_dir: str | Path | None = None,
) -> dict[str, Any]:
    source_path = _validate_pdf_path(source_pdf)

    if candidate_window_before < 0 or candidate_window_after < 0:
        raise ValueError("candidate windows must be non-negative")

    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")

    total_pages = count_pdf_pages(source_path)
    anchor_topic = _pick_anchor_topic(topics)

    if anchor_topic is None:
        return {
            "detected": False,
            "offset": None,
            "reason": "No reliable topic anchor with start_printed and heading/title.",
            "best_candidate": None,
            "candidates": [],
        }

    printed_start = int(anchor_topic["start_printed"])
    topic_label = _build_topic_label(anchor_topic)
    candidate_pages = _candidate_pages(
        printed_start=printed_start,
        total_pages=total_pages,
        candidate_window_before=candidate_window_before,
        candidate_window_after=candidate_window_after,
    )

    candidates: list[dict[str, Any]] = []

    if temp_dir is None:
        with tempfile.TemporaryDirectory(prefix="ai_extract_offset_") as temp_root:
            candidates = _evaluate_candidates(
                source_path=source_path,
                temp_root=Path(temp_root),
                candidate_pages=candidate_pages,
                printed_start=printed_start,
                topic_label=topic_label,
                model=model,
            )
    else:
        temp_root = Path(temp_dir)
        temp_root.mkdir(parents=True, exist_ok=True)
        candidates = _evaluate_candidates(
            source_path=source_path,
            temp_root=temp_root,
            candidate_pages=candidate_pages,
            printed_start=printed_start,
            topic_label=topic_label,
            model=model,
        )

    best_candidate = _best_candidate(candidates)

    for candidate in candidates:
        if (
            candidate.get("is_start") is True
            and float(candidate.get("confidence") or 0.0) >= min_confidence
        ):
            return {
                "detected": True,
                "offset": candidate["offset"],
                "anchor_topic": _public_anchor(anchor_topic),
                "actual_page": candidate["actual_page"],
                "confidence": candidate["confidence"],
                "reason": candidate.get("reason") or "",
                "candidates": candidates,
            }

    return {
        "detected": False,
        "offset": None,
        "reason": "Could not confidently detect page offset.",
        "best_candidate": best_candidate,
        "candidates": candidates,
    }


def _validate_pdf_path(source_pdf: str | Path) -> Path:
    path = Path(source_pdf)

    if not path.exists():
        raise ValueError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF file must have a .pdf extension: {path}")

    return path


def _pick_anchor_topic(topics: list[dict]) -> dict | None:
    if not isinstance(topics, list):
        raise ValueError("topics must be a list")

    for topic in topics:
        if not isinstance(topic, dict):
            continue

        start_printed = topic.get("start_printed")
        label = _build_topic_label(topic)

        if start_printed is None or not label:
            continue

        try:
            int(start_printed)
        except (TypeError, ValueError):
            continue

        return topic

    return None


def _build_topic_label(topic: dict) -> str:
    heading = str(topic.get("heading") or "").strip().rstrip(".")
    title = str(topic.get("title") or "").strip()

    if heading and title:
        return f"{heading}: {title}"

    return heading or title


def _candidate_pages(
    *,
    printed_start: int,
    total_pages: int,
    candidate_window_before: int,
    candidate_window_after: int,
) -> list[int]:
    start = max(1, printed_start - candidate_window_before)
    end = min(total_pages, printed_start + candidate_window_after)
    return list(range(start, end + 1))


def _evaluate_candidates(
    *,
    source_path: Path,
    temp_root: Path,
    candidate_pages: list[int],
    printed_start: int,
    topic_label: str,
    model: str | None,
) -> list[dict[str, Any]]:
    verify_prompt = build_topic_verify_prompt(topic_label)
    candidates = []

    for actual_page in candidate_pages:
        offset = actual_page - printed_start
        single_page_pdf = temp_root / f"verify_page_{actual_page}.pdf"
        candidate: dict[str, Any] = {
            "actual_page": actual_page,
            "offset": offset,
            "is_start": False,
            "confidence": 0.0,
            "reason": "",
        }

        try:
            make_single_page_pdf(
                source_pdf=source_path,
                output_pdf=single_page_pdf,
                page_number=actual_page,
            )
            raw_response = generate_with_pdf(
                prompt=verify_prompt,
                pdf_path=single_page_pdf,
                model=model,
            )
            parsed = parse_json_loose(raw_response)
            candidate.update(_parse_verify_result(parsed))

        except Exception as exc:
            candidate["error"] = str(exc)

        candidates.append(candidate)

    return candidates


def _parse_verify_result(payload: dict) -> dict[str, Any]:
    is_start = payload.get("is_start")

    if is_start is None:
        is_start = payload.get("match")

    confidence = _to_float(payload.get("confidence"))
    reason = str(payload.get("reason") or "").strip()

    return {
        "is_start": _to_bool(is_start),
        "confidence": confidence,
        "reason": reason,
    }


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}

    return bool(value)


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(parsed, 1.0))


def _best_candidate(candidates: list[dict[str, Any]]) -> dict | None:
    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (
            item.get("is_start") is True,
            float(item.get("confidence") or 0.0),
        ),
    )


def _public_anchor(topic: dict) -> dict:
    return {
        "name": topic.get("name"),
        "heading": topic.get("heading"),
        "title": topic.get("title"),
        "start_printed": topic.get("start_printed"),
    }
