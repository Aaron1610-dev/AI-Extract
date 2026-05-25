from __future__ import annotations

from dotenv import dotenv_values, load_dotenv

from app.core.paths import CORE_DIR


CONFIG_ENV_PATH = CORE_DIR / "config.env"


class Settings:
    def __init__(self) -> None:
        if CONFIG_ENV_PATH.exists():
            load_dotenv(CONFIG_ENV_PATH)

        values = dotenv_values(CONFIG_ENV_PATH) if CONFIG_ENV_PATH.exists() else {}

        self.APP_NAME = str(values.get("APP_NAME") or "AI-Extract")
        self.APP_ENV = str(values.get("APP_ENV") or "development")
        self.APP_HOST = str(values.get("APP_HOST") or "0.0.0.0")
        self.APP_PORT = int(values.get("APP_PORT") or 8101)

        self.GEMINI_MODEL = str(values.get("GEMINI_MODEL") or "gemini-2.5-flash")

        self.GEMINI_MIN_INTERVAL = float(values.get("GEMINI_MIN_INTERVAL") or 4.5)
        self.GEMINI_COOLDOWN_SECONDS = int(values.get("GEMINI_COOLDOWN_SECONDS") or 300)

        self.CONFIG_ENV_PATH = CONFIG_ENV_PATH


settings = Settings()
