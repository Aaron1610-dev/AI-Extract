from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.prompts.keyword_prompts import build_keyword_prompt, list_prompt_versions
from app.schemas.keyword import (
    KeywordExtractRequest,
    KeywordExtractResponse,
    KeywordPromptDebugRequest,
    KeywordPromptDebugResponse,
)
from app.services.gemini.keyword_service import (
    extract_query_keywords,
    extract_query_keywords_local_debug,
    extract_query_keywords_with_analysis,
)
router = APIRouter(prefix="/api/keywords", tags=["keywords"])


@router.get("/prompt-versions")
def get_prompt_versions() -> dict:
    return {
        "prompt_versions": list_prompt_versions()
    }


@router.post("/debug-prompt", response_model=KeywordPromptDebugResponse)
def debug_prompt(request: KeywordPromptDebugRequest) -> dict:
    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query must not be empty.",
        )

    try:
        prompt = build_keyword_prompt(
            input_text=query,
            max_keywords=request.max_keywords,
            prompt_version=request.prompt_version,
        )

        return {
            "query": query,
            "max_keywords": request.max_keywords,
            "prompt_version": request.prompt_version,
            "prompt": prompt,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post("/debug-filter")
def debug_filter_keywords(payload: dict) -> dict:
    raw_keywords = payload.get("raw_keywords", [])
    max_keywords = int(payload.get("max_keywords", 10))

    return extract_query_keywords_local_debug(
        raw_keywords=raw_keywords,
        max_keywords=max_keywords,
    )


@router.post("/extract", response_model=KeywordExtractResponse)
def extract_keywords(request: KeywordExtractRequest) -> dict:
    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query must not be empty.",
        )

    try:
        return extract_query_keywords(
            input_text=query,
            max_keywords=request.max_keywords,
            model=request.model,
            prompt_version=request.prompt_version,
            include_raw_response=request.include_raw_response,
            wait_for_available_key=request.wait_for_available_key,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Keyword extraction failed: {exc}",
        ) from exc
    
@router.post("/extract-analysis")
def extract_keywords_with_analysis(request: KeywordExtractRequest) -> dict:
    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query must not be empty.",
        )

    try:
        return extract_query_keywords_with_analysis(
            input_text=query,
            max_keywords=request.max_keywords,
            model=request.model,
            include_raw_response=request.include_raw_response,
            wait_for_available_key=request.wait_for_available_key,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Keyword analysis extraction failed: {exc}",
        ) from exc
