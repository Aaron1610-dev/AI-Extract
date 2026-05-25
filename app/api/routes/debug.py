from __future__ import annotations

from fastapi import APIRouter

from app.services.gemini.client import get_gemini_rotation_status

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/gemini-keys")
def gemini_keys_status() -> dict:
    return get_gemini_rotation_status()
