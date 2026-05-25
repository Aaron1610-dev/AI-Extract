from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from dotenv import dotenv_values, load_dotenv

from app.core.paths import BASE_DIR

_log = logging.getLogger(__name__)

CONFIG_ENV_PATH = BASE_DIR / "app" / "core" / "config.env"
STATE_FILE_PATH = BASE_DIR / "app" / "core" / "gemini_rotation_state.json"

_ROTATABLE_PATTERNS = [
    "resource_exhausted",
    "rate_limit",
    "ratelimitexceeded",
    "quota",
    "429",
    "503",
    "unavailable",
    "service unavailable",
    "deadline exceeded",
    "deadline_exceeded",
    "timeout",
    "timed out",
    "bad gateway",
    "internal server error",
    "connection reset",
    "connection refused",
    "high demand",
]

_DEAD_KEY_PATTERNS = [
    "api_key_invalid",
    "api key invalid",
    "api key expired",
    "invalid api key",
    "api key not valid",
    "invalidapikey",
    "key expired",
    "expired api key",
    "key has expired",
    "consumer_suspended",
    "consumer has been suspended",
    "has been suspended",
    "key suspended",
    "api key suspended",
    "reported as leaked",
    "your api key was reported as leaked",
]

_default_pool: GeminiRotationPool | None = None
_default_pool_lock = threading.Lock()


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:8] + "***" + key[-3:]


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_rotatable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _ROTATABLE_PATTERNS) or _is_dead_key_error(exc)


def _is_dead_key_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _DEAD_KEY_PATTERNS)


def _error_label(exc: Exception) -> str:
    message = str(exc).lower()

    if "reported as leaked" in message:
        return "reported-as-leaked"

    if _is_dead_key_error(exc):
        if "suspended" in message:
            return "suspended-key"
        return "invalid-or-expired-key"

    if "429" in message or "quota" in message or "rate" in message:
        return "quota-or-rate-limit"

    if "503" in message or "unavailable" in message or "high demand" in message:
        return "service-unavailable"

    return "temporary-error"


def _read_env_values() -> dict[str, str]:
    values: dict[str, str] = {}

    if CONFIG_ENV_PATH.exists():
        for key, value in dotenv_values(CONFIG_ENV_PATH).items():
            if value is not None:
                values[key] = str(value)

        load_dotenv(CONFIG_ENV_PATH)

    # Runtime env has higher priority.
    for key, value in os.environ.items():
        if key.startswith("GEMINI_"):
            values[key] = value

    return values


def _load_gemini_config() -> dict[str, Any]:
    values = _read_env_values()

    raw_keys = str(values.get("GEMINI_API_KEYS") or "").strip()
    keys = [item.strip() for item in raw_keys.split(",") if item.strip()]

    if not keys:
        raise RuntimeError(
            "No Gemini API keys found. Please set GEMINI_API_KEYS=key1,key2,key3 in app/core/config.env"
        )

    try:
        min_interval = float(values.get("GEMINI_MIN_INTERVAL") or 4.5)
    except Exception:
        min_interval = 4.5

    try:
        cooldown_seconds = int(values.get("GEMINI_COOLDOWN_SECONDS") or 300)
    except Exception:
        cooldown_seconds = 300

    labels = [f"GEMINI_API_KEY_{idx + 1}" for idx in range(len(keys))]

    return {
        "keys": keys,
        "labels": labels,
        "min_interval": min_interval,
        "cooldown_seconds": cooldown_seconds,
    }


class GeminiRotationPool:
    def __init__(
        self,
        keys: list[str],
        *,
        labels: list[str],
        min_interval: float = 4.5,
        cooldown_seconds: int = 300,
        state_file: Path = STATE_FILE_PATH,
    ) -> None:
        if not keys:
            raise ValueError("GeminiRotationPool requires at least one API key")

        self._keys = keys
        self._labels = labels
        self._n = len(keys)
        self._min_interval = min_interval
        self._cooldown_seconds = cooldown_seconds
        self._state_file = state_file

        self._lock = threading.Lock()
        self._key_locks = {idx: threading.Lock() for idx in range(self._n)}

        self._next_idx = 0
        self._call_count = 0
        self._cycle_count = 0

        self._last_call_time: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}
        self._dead_keys: set[int] = set()
        self._dead_reasons: dict[int, str] = {}
        self._dead_at_epoch: dict[int, float] = {}

        self._load_state()

        _log.info(
            "[gemini_client] Loaded %d Gemini key(s), next=%s, state_file=%s",
            self._n,
            self._labels[self._next_idx],
            self._state_file,
        )

    def _build_state(self) -> dict[str, Any]:
        now_wall = time.time()
        now_mono = time.monotonic()

        keys_payload = []

        for idx, key in enumerate(self._keys):
            cooldown_remaining = self._cooldown_until.get(idx, 0.0) - now_mono
            cooldown_until_epoch = (
                now_wall + cooldown_remaining
                if cooldown_remaining > 0
                else None
            )

            item = {
                "index": idx,
                "label": self._labels[idx],
                "key_hash": _key_hash(key),
                "cooldown_until_epoch": cooldown_until_epoch,
                "is_dead": idx in self._dead_keys,
                "dead_reason": self._dead_reasons.get(idx),
                "dead_at_epoch": self._dead_at_epoch.get(idx),
            }

            keys_payload.append(item)

        return {
            "saved_at_epoch": now_wall,
            "next_idx": self._next_idx,
            "call_count": self._call_count,
            "cycle_count": self._cycle_count,
            "keys": keys_payload,
        }

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_file.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(self._build_state(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_path, self._state_file)
        except Exception as exc:
            _log.warning("[gemini_client] Failed to save state: %s", exc)

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return

        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("[gemini_client] Failed to read state file: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        saved_next_idx = payload.get("next_idx")
        if isinstance(saved_next_idx, int) and 0 <= saved_next_idx < self._n:
            self._next_idx = saved_next_idx

        saved_call_count = payload.get("call_count")
        if isinstance(saved_call_count, int) and saved_call_count >= 0:
            self._call_count = saved_call_count

        saved_cycle_count = payload.get("cycle_count")
        if isinstance(saved_cycle_count, int) and saved_cycle_count >= 0:
            self._cycle_count = saved_cycle_count

        now_wall = time.time()
        now_mono = time.monotonic()

        for item in payload.get("keys", []):
            if not isinstance(item, dict):
                continue

            idx = item.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= self._n:
                continue

            saved_hash = item.get("key_hash")
            if saved_hash != _key_hash(self._keys[idx]):
                continue

            if item.get("is_dead"):
                self._dead_keys.add(idx)
                self._dead_reasons[idx] = str(item.get("dead_reason") or "dead-key")
                dead_at = item.get("dead_at_epoch")
                if isinstance(dead_at, (int, float)):
                    self._dead_at_epoch[idx] = float(dead_at)
                continue

            cooldown_until_epoch = item.get("cooldown_until_epoch")
            if isinstance(cooldown_until_epoch, (int, float)):
                remaining = float(cooldown_until_epoch) - now_wall
                if remaining > 0:
                    self._cooldown_until[idx] = now_mono + remaining

    def _in_cooldown_or_dead(self, idx: int) -> bool:
        now = time.monotonic()
        return idx in self._dead_keys or now < self._cooldown_until.get(idx, 0.0)

    def _pace_key(self, idx: int) -> None:
        last_call = self._last_call_time.get(idx, 0.0)
        wait_seconds = self._min_interval - (time.monotonic() - last_call)

        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _set_cooldown(self, idx: int) -> None:
        self._cooldown_until[idx] = time.monotonic() + self._cooldown_seconds

        _log.warning(
            "[gemini_client] Key %s entered cooldown for %ds",
            self._labels[idx],
            self._cooldown_seconds,
        )

        self._save_state()

    def _mark_dead(self, idx: int, reason: str) -> None:
        self._dead_keys.add(idx)
        self._dead_reasons[idx] = reason
        self._dead_at_epoch[idx] = time.time()

        _log.warning(
            "[gemini_client] Key %s marked dead: %s",
            self._labels[idx],
            reason,
        )

        self._save_state()

    def _earliest_available_wait(self) -> float:
        now = time.monotonic()
        waits: list[float] = []

        for idx in range(self._n):
            if idx in self._dead_keys:
                continue

            remaining = self._cooldown_until.get(idx, 0.0) - now
            waits.append(max(0.0, remaining))

        if not waits:
            return 1.0

        return min(waits)

    def run(
        self,
        operation: Callable[[int, str, str], str],
        *,
        wait_for_available_key: bool = False,
        max_wait_seconds: int = 3600,
        status_callback: Callable[[dict], None] | None = None,
    ) -> str:
        started = time.monotonic()
        last_err: Exception | None = None

        while True:
            with self._lock:
                start_idx = self._next_idx

            tried_labels: list[str] = []

            for offset in range(self._n):
                idx = (start_idx + offset) % self._n
                label = self._labels[idx]
                key = self._keys[idx]

                if self._in_cooldown_or_dead(idx):
                    continue

                tried_labels.append(label)

                with self._key_locks[idx]:
                    if self._in_cooldown_or_dead(idx):
                        continue

                    self._pace_key(idx)

                    _log.info(
                        "[gemini_client] Using %s (%s)",
                        label,
                        _mask_key(key),
                    )

                    if status_callback:
                        status_callback({
                            "event": "key_selected",
                            "key_label": label,
                            "key_masked": _mask_key(key),
                        })

                    try:
                        result = operation(idx, label, key)
                        self._last_call_time[idx] = time.monotonic()

                    except Exception as exc:
                        last_err = exc

                        if _is_rotatable_error(exc):
                            reason = _error_label(exc)

                            if _is_dead_key_error(exc):
                                self._mark_dead(idx, reason)
                                event = "key_dead"
                            else:
                                self._set_cooldown(idx)
                                event = "key_cooldown"

                            if status_callback:
                                status_callback({
                                    "event": event,
                                    "key_label": label,
                                    "key_masked": _mask_key(key),
                                    "reason": reason,
                                })

                            continue

                        raise

                with self._lock:
                    self._next_idx = (idx + 1) % self._n
                    self._call_count += 1

                    if self._call_count % self._n == 0:
                        self._cycle_count += 1

                    next_label = self._labels[self._next_idx]

                _log.info(
                    "[gemini_client] Success with %s. Next key: %s",
                    label,
                    next_label,
                )

                self._save_state()

                if status_callback:
                    status_callback({
                        "event": "success",
                        "key_label": label,
                        "key_masked": _mask_key(key),
                        "next_key_label": next_label,
                        "call_count": self._call_count,
                        "cycle_count": self._cycle_count,
                    })

                return result

            if not wait_for_available_key:
                raise RuntimeError(
                    f"All Gemini API keys are exhausted, dead, or in cooldown. "
                    f"Tried={tried_labels}. Last error={last_err}"
                )

            live_count = self._n - len(self._dead_keys)
            if live_count <= 0:
                raise RuntimeError(
                    f"All Gemini API keys are dead. Last error={last_err}"
                )

            elapsed = time.monotonic() - started
            if elapsed >= max_wait_seconds:
                raise RuntimeError(
                    f"Max wait exceeded while waiting for Gemini key. "
                    f"max_wait_seconds={max_wait_seconds}, last_error={last_err}"
                )

            wait_seconds = min(
                self._earliest_available_wait() + 1.0,
                max_wait_seconds - elapsed,
            )

            _log.info(
                "[gemini_client] All keys unavailable. Sleeping %.1fs",
                wait_seconds,
            )

            if status_callback:
                status_callback({
                    "event": "all_keys_waiting",
                    "wait_seconds": round(wait_seconds, 1),
                })

            time.sleep(wait_seconds)

    def rotation_status(self) -> dict[str, Any]:
        now = time.monotonic()

        keys = []

        for idx, key in enumerate(self._keys):
            cooldown_remaining = max(
                0.0,
                self._cooldown_until.get(idx, 0.0) - now,
            )

            keys.append({
                "index": idx,
                "label": self._labels[idx],
                "masked": _mask_key(key),
                "in_cooldown": cooldown_remaining > 0,
                "cooldown_remaining_s": round(cooldown_remaining, 1),
                "is_dead": idx in self._dead_keys,
                "dead_reason": self._dead_reasons.get(idx),
            })

        return {
            "total_keys": self._n,
            "next_idx": self._next_idx,
            "next_key_label": self._labels[self._next_idx],
            "next_key_masked": _mask_key(self._keys[self._next_idx]),
            "call_count": self._call_count,
            "cycle_count": self._cycle_count,
            "state_file": str(self._state_file),
            "keys": keys,
        }


def _get_default_pool() -> GeminiRotationPool:
    global _default_pool

    if _default_pool is None:
        with _default_pool_lock:
            if _default_pool is None:
                config = _load_gemini_config()

                _default_pool = GeminiRotationPool(
                    keys=config["keys"],
                    labels=config["labels"],
                    min_interval=config["min_interval"],
                    cooldown_seconds=config["cooldown_seconds"],
                    state_file=STATE_FILE_PATH,
                )

    return _default_pool


def _call_gemini_http(prompt: str, api_key: str, model: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )

    body = json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body[:800]}")

    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError: {exc.reason}")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected Gemini response structure: {str(data)[:500]}")

    if not text:
        raise RuntimeError("Gemini returned empty response text")

    return text


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF file must have a .pdf extension: {path}")

    return path


def _call_gemini_with_pdf_sdk(
    prompt: str,
    pdf_path: Path,
    api_key: str,
    model: str,
    mime_type: str,
) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required for PDF Gemini generation. "
            "Install dependencies from requirements.txt."
        ) from exc

    client = genai.Client(api_key=api_key)
    uploaded_file = None

    try:
        upload_kwargs: dict[str, Any] = {"file": str(pdf_path)}
        upload_config_cls = getattr(types, "UploadFileConfig", None)

        if upload_config_cls is not None:
            upload_kwargs["config"] = upload_config_cls(mime_type=mime_type)

        try:
            uploaded_file = client.files.upload(**upload_kwargs)
        except TypeError:
            if "config" not in upload_kwargs:
                raise
            uploaded_file = client.files.upload(file=str(pdf_path))

        response = client.models.generate_content(
            model=model,
            contents=[prompt, uploaded_file],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

    except Exception as exc:
        raise RuntimeError(f"Gemini PDF generation failed: {exc}") from exc

    finally:
        file_name = getattr(uploaded_file, "name", None)
        if file_name:
            try:
                client.files.delete(name=file_name)
            except Exception as exc:
                _log.warning(
                    "[gemini_client] Failed to delete uploaded Gemini file %s: %s",
                    file_name,
                    exc,
                )

    text = getattr(response, "text", None)

    if not text:
        raise RuntimeError("Gemini returned empty response text")

    return text


def generate_text(
    prompt: str,
    model: str = "gemini-2.5-flash",
    wait_for_available_key: bool = False,
    max_wait_seconds: int = 3600,
    status_callback: Callable[[dict], None] | None = None,
) -> str:
    pool = _get_default_pool()

    def operation(_idx: int, _label: str, api_key: str) -> str:
        return _call_gemini_http(
            prompt=prompt,
            api_key=api_key,
            model=model,
        )

    return pool.run(
        operation,
        wait_for_available_key=wait_for_available_key,
        max_wait_seconds=max_wait_seconds,
        status_callback=status_callback,
    )


def generate_with_pdf(
    prompt: str,
    pdf_path: str | Path,
    model: str | None = None,
    mime_type: str = "application/pdf",
    wait_for_available_key: bool = False,
    max_wait_seconds: int = 3600,
    status_callback: Callable[[dict], None] | None = None,
) -> str:
    path = _validate_pdf_path(pdf_path)
    selected_model = model or "gemini-2.5-flash"

    if mime_type != "application/pdf":
        raise ValueError("Only application/pdf is supported for PDF generation")

    pool = _get_default_pool()

    def operation(_idx: int, _label: str, api_key: str) -> str:
        return _call_gemini_with_pdf_sdk(
            prompt=prompt,
            pdf_path=path,
            api_key=api_key,
            model=selected_model,
            mime_type=mime_type,
        )

    return pool.run(
        operation,
        wait_for_available_key=wait_for_available_key,
        max_wait_seconds=max_wait_seconds,
        status_callback=status_callback,
    )


def get_gemini_rotation_status() -> dict[str, Any]:
    return _get_default_pool().rotation_status()
