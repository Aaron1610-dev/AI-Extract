"""JSON parsing and normalization helpers for Topic/Lesson extraction."""

from __future__ import annotations

import json
import re
from typing import Any


_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def parse_json_loose(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Cannot parse empty Gemini response as JSON")

    candidates = [text.strip()]

    fence_match = _CODE_FENCE_RE.match(text)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    extracted = _extract_first_json_object(text)
    if extracted:
        candidates.append(extracted)

    last_error: Exception | None = None

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

        if not isinstance(parsed, dict):
            raise ValueError("Gemini JSON response must be an object")

        return parsed

    raise ValueError(f"Failed to parse Gemini response as JSON: {last_error}")


def normalize_topic_lesson_payload(
    payload: dict,
    total_pdf_pages: int | None = None,
    offset: int | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Topic/Lesson payload must be a JSON object")

    topics_raw = payload.get("topics")
    lessons_raw = payload.get("lessons")

    if not isinstance(topics_raw, list):
        topics_raw = []

    if not isinstance(lessons_raw, list):
        lessons_raw = []

    return {
        "topics": [
            _normalize_item(
                item,
                prefix="topic",
                index=index,
                total_pdf_pages=total_pdf_pages,
                offset=offset,
            )
            for index, item in enumerate(topics_raw, start=1)
            if isinstance(item, dict)
        ],
        "lessons": [
            _normalize_item(
                item,
                prefix="lesson",
                index=index,
                total_pdf_pages=total_pdf_pages,
                offset=offset,
            )
            for index, item in enumerate(lessons_raw, start=1)
            if isinstance(item, dict)
        ],
        "raw_payload": payload,
        "offset": offset,
    }


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")

    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return None


def _normalize_item(
    item: dict[str, Any],
    *,
    prefix: str,
    index: int,
    total_pdf_pages: int | None,
    offset: int | None,
) -> dict:
    name = _clean_string(item.get("name")) or f"{prefix}_{index:02d}"
    heading = _clean_string(item.get("heading"))
    title = _clean_string(item.get("title")) or heading or name

    start_printed = _to_int(item.get("start_printed"))
    end_printed = _to_int(item.get("end_printed"))

    if end_printed is None and start_printed is not None:
        end_printed = start_printed

    start = _to_int(item.get("start"))
    end = _to_int(item.get("end"))

    if start is None and start_printed is not None and offset is not None:
        start = start_printed + offset

    if end is None and end_printed is not None and offset is not None:
        end = end_printed + offset

    if end is None and start is not None:
        end = start

    if start is None and end is not None:
        start = end

    if start is not None and end is not None:
        start, end = _normalize_range(start, end, total_pdf_pages)

    normalized = {
        "name": name,
        "start_printed": start_printed,
        "end_printed": end_printed,
        "start": start,
        "end": end,
        "heading": heading,
        "title": title,
    }

    return normalized


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float) and value.is_integer():
        return int(value)

    text = str(value).strip()

    if not text:
        return None

    match = re.search(r"-?\d+", text)

    if not match:
        return None

    return int(match.group(0))


def _normalize_range(
    start: int,
    end: int,
    total_pdf_pages: int | None,
) -> tuple[int, int]:
    if end < start:
        start, end = end, start

    if total_pdf_pages is not None:
        if total_pdf_pages < 1:
            raise ValueError("total_pdf_pages must be greater than 0")

        start = max(1, min(start, total_pdf_pages))
        end = max(1, min(end, total_pdf_pages))

        if end < start:
            end = start

    return start, end
