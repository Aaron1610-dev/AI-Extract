from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordExtractRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User search query")
    max_keywords: int = Field(default=10, ge=1, le=20)
    model: str = Field(default="gemini-2.5-flash")
    prompt_version: str = Field(default="strict")
    include_raw_response: bool = Field(default=False)
    wait_for_available_key: bool = Field(default=False)


class KeywordExtractResponse(BaseModel):
    query: str
    raw_keywords: list[str]
    filtered_keywords: list[str]
    model: str
    prompt_version: str
    raw_response: str | None = None


class KeywordPromptDebugRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_keywords: int = Field(default=10, ge=1, le=20)
    prompt_version: str = Field(default="strict")


class KeywordPromptDebugResponse(BaseModel):
    query: str
    max_keywords: int
    prompt_version: str
    prompt: str