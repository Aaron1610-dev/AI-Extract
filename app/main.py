from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.debug import router as debug_router
from app.api.routes.extract_chunks_debug import router as extract_chunks_debug_router
from app.api.routes.extract_jobs import router as extract_jobs_router
from app.api.routes.extract_lessons import router as extract_lessons_router
from app.api.routes.extract_topics import router as extract_topics_router
from app.api.routes.health import router as health_router
from app.api.routes.keywords import router as keywords_router
from app.core.config import settings
from app.core.logging import setup_logging


setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="A small Gemini-powered keyword extraction backend service.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(keywords_router)
app.include_router(extract_jobs_router)
app.include_router(extract_topics_router)
app.include_router(extract_lessons_router)
app.include_router(extract_chunks_debug_router)
app.include_router(debug_router)
