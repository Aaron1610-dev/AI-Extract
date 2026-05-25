from __future__ import annotations

from app.prompts.keyword_prompts import build_keyword_prompt
from app.services.gemini.client import generate_text
from app.utils.json_utils import extract_json, normalize_for_compare


_NOISE_TERMS: frozenset[str] = frozenset([
    "tim",
    "tim kiem",
    "tim hieu",
    "muon",
    "toi muon",
    "cho toi",
    "giup toi",
    "thong tin",
    "thong tin ve",
    "ve",
    "giai thich",
    "huong dan",
    "cach",
    "la gi",
    "hoi",
    "tra loi",
])

_BAD_PREFIXES = (
    "thong tin ",
    "thong tin ve ",
    "tim kiem ",
    "tim hieu ",
    "giai thich ",
    "huong dan ",
    "cach ",
)

_MAX_QUERY_KW_WORDS = 6


def filter_keywords(keywords: list, max_keywords: int = 10) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        if not isinstance(kw, str):
            continue

        kw = kw.strip()
        if not kw:
            continue

        if len(kw.split()) > _MAX_QUERY_KW_WORDS:
            continue

        norm = normalize_for_compare(kw)

        if not norm:
            continue

        if norm in _NOISE_TERMS:
            continue

        if any(norm.startswith(prefix) for prefix in _BAD_PREFIXES):
            continue

        if norm in seen:
            continue

        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]


def extract_query_keywords_local_debug(
    raw_keywords: list,
    max_keywords: int = 10,
) -> dict:
    filtered = filter_keywords(raw_keywords, max_keywords=max_keywords)

    return {
        "raw_keywords": raw_keywords,
        "filtered_keywords": filtered,
    }


def extract_query_keywords(
    input_text: str,
    *,
    max_keywords: int = 10,
    model: str = "gemini-2.5-flash",
    prompt_version: str = "strict",
    include_raw_response: bool = False,
    wait_for_available_key: bool = False,
) -> dict:
    prompt = build_keyword_prompt(
        input_text=input_text,
        max_keywords=max_keywords,
        prompt_version=prompt_version,
    )

    raw_response = generate_text(
        prompt=prompt,
        model=model,
        wait_for_available_key=wait_for_available_key,
    )

    parsed = extract_json(raw_response)

    raw_keywords = parsed.get("keywords", [])

    if not isinstance(raw_keywords, list):
        raw_keywords = []

    filtered_keywords = filter_keywords(
        raw_keywords,
        max_keywords=max_keywords,
    )

    return {
        "query": input_text,
        "raw_keywords": raw_keywords,
        "filtered_keywords": filtered_keywords,
        "model": model,
        "prompt_version": prompt_version,
        "raw_response": raw_response if include_raw_response else None,
    }

def extract_query_keywords_with_analysis(
    input_text: str,
    *,
    max_keywords: int = 10,
    model: str = "gemini-2.5-flash",
    include_raw_response: bool = False,
    wait_for_available_key: bool = False,
) -> dict:
    prompt = build_keyword_prompt(
        input_text=input_text,
        max_keywords=max_keywords,
        prompt_version="analysis",
    )

    raw_response = generate_text(
        prompt=prompt,
        model=model,
        wait_for_available_key=wait_for_available_key,
    )

    parsed = extract_json(raw_response)

    keyword_analysis = parsed.get("keyword_analysis", [])
    if not isinstance(keyword_analysis, list):
        keyword_analysis = []

    raw_search_keywords = parsed.get("search_keywords", [])
    if not isinstance(raw_search_keywords, list):
        raw_search_keywords = []

    filtered_search_keywords = filter_keywords(
        raw_search_keywords,
        max_keywords=max_keywords,
    )

    return {
        "query": input_text,
        "subject": parsed.get("subject") or "",
        "grade_candidates": parsed.get("grade_candidates") or [],
        "topic_candidates": parsed.get("topic_candidates") or [],
        "keyword_analysis": keyword_analysis,
        "search_keywords": filtered_search_keywords,
        "debug_notes": parsed.get("debug_notes") or [],
        "model": model,
        "prompt_version": "analysis",
        "raw_response": raw_response if include_raw_response else None,
    }
