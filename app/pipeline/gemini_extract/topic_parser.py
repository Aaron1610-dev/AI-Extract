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

    topics = [
        _normalize_item(item, prefix="topic", index=index)
        for index, item in enumerate(topics_raw, start=1)
        if isinstance(item, dict)
    ]
    lessons = [
        _normalize_item(item, prefix="lesson", index=index)
        for index, item in enumerate(lessons_raw, start=1)
        if isinstance(item, dict)
    ]

    topics, lessons = fill_end_printed_from_starts(
        topics=topics,
        lessons=lessons,
        printed_end_of_main=_to_int(payload.get("printed_end_of_main")),
    )

    if offset is not None:
        topics = [
            _apply_offset(item, offset=offset, total_pdf_pages=total_pdf_pages)
            for item in topics
        ]
        lessons = [
            _apply_offset(item, offset=offset, total_pdf_pages=total_pdf_pages)
            for item in lessons
        ]
    else:
        topics = [_clamp_existing_range(item, total_pdf_pages) for item in topics]
        lessons = [_clamp_existing_range(item, total_pdf_pages) for item in lessons]

    return {
        "topics": topics,
        "lessons": lessons,
        "raw_payload": payload,
        "offset": offset,
    }


def fill_end_printed_from_starts(
    topics: list[dict],
    lessons: list[dict],
    printed_end_of_main: int | None = None,
) -> tuple[list[dict], list[dict]]:
    return (
        _fill_group_end_printed(topics, printed_end_of_main),
        _fill_group_end_printed(lessons, printed_end_of_main),
    )


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

    if end is None and start is not None:
        end = start

    if start is None and end is not None:
        start = end

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


def _fill_group_end_printed(
    items: list[dict],
    printed_end_of_main: int | None,
) -> list[dict]:
    sortable = [item for item in items if item.get("start_printed") is not None]
    unsorted = [item for item in items if item.get("start_printed") is None]

    sortable.sort(key=lambda item: int(item["start_printed"]))

    for index, item in enumerate(sortable):
        if index + 1 < len(sortable):
            item["end_printed"] = int(sortable[index + 1]["start_printed"]) - 1
        elif printed_end_of_main is not None:
            item["end_printed"] = printed_end_of_main
        elif item.get("end_printed") is None:
            item["end_printed"] = item.get("start_printed")

    for item in unsorted:
        if item.get("end_printed") is None:
            item["end_printed"] = item.get("start_printed")

    return sortable + unsorted


def _apply_offset(
    item: dict,
    *,
    offset: int,
    total_pdf_pages: int | None,
) -> dict:
    out = dict(item)

    if out.get("start_printed") is not None:
        out["start"] = int(out["start_printed"]) + offset

    if out.get("end_printed") is not None:
        out["end"] = int(out["end_printed"]) + offset

    if out.get("end") is None and out.get("start") is not None:
        out["end"] = out["start"]

    if out.get("start") is None and out.get("end") is not None:
        out["start"] = out["end"]

    return _clamp_existing_range(out, total_pdf_pages)


def _clamp_existing_range(item: dict, total_pdf_pages: int | None) -> dict:
    out = dict(item)
    start = out.get("start")
    end = out.get("end")

    if start is not None and end is not None:
        out["start"], out["end"] = _normalize_range(
            int(start),
            int(end),
            total_pdf_pages,
        )

    return out


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
