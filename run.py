from __future__ import annotations

import uvicorn

from app.core.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
        # Do not watch workspace/: extraction and Kaggle flows write generated files there.
        reload_dirs=["app"],
        reload_excludes=[
            "workspace/*",
            "workspace/**",
            "logs/*",
            "logs/**",
            "__pycache__/*",
            "__pycache__/**",
            ".git/*",
            ".git/**",
            ".venv/*",
            ".venv/**",
            "venv/*",
            "venv/**",
        ],
    )
