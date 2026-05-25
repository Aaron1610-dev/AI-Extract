from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


def normalize_for_compare(text: str) -> str:
    """
    Normalize text for keyword comparison.

    Example:
    "Thông tin về Python!" -> "thong tin ve python"
    """
    if not isinstance(text, str):
        return ""

    text = text.strip().lower()
    text = unicodedata.normalize("NFD", text)

    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) != "Mn"
    )

    text = re.sub(r"[^\w\s+#.-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def extract_json(raw_text: str) -> dict[str, Any]:
    """
    Extract JSON object from Gemini raw response.

    Gemini should return JSON only, but sometimes it may return:
    ```json
    {"keywords": ["Python"]}
    ```

    This function tries to robustly parse the first JSON object.
    """
    if not isinstance(raw_text, str):
        return {}

    text = raw_text.strip()

    if not text:
        return {}

    # Remove markdown fences if any.
    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"```$", "", text.strip())

    # Try direct parse first.
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    # Fallback: find the first {...} block.
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return {}

    candidate = text[start:end + 1]

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}