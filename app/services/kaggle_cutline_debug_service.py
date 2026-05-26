from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.core.paths import CORE_DIR
from app.core.paths import BASE_DIR, WORKSPACE_DIR
from app.services.storage.workspace_service import read_json, write_json


KERNEL_SOURCE_DIR = BASE_DIR / "app" / "pipeline" / "kaggle_kernels" / "debug-cutline-one-chunk"
DEFAULT_WORK_DIR = WORKSPACE_DIR / "kaggle_cutline_debug"
DEFAULT_POLL_SECONDS = 20
DEFAULT_TIMEOUT_SECONDS = 1800
REQUIRED_ENV_KEYS = [
    "AI_EXTRACT_KAGGLE_USERNAME",
    "AI_EXTRACT_KAGGLE_KEY",
    "AI_EXTRACT_KAGGLE_DATASET_SLUG",
    "AI_EXTRACT_KAGGLE_KERNEL_REF",
]


class KaggleCutlineDebugNotConfigured(RuntimeError):
    pass


class KaggleCutlineDebugError(RuntimeError):
    pass


@dataclass(frozen=True)
class KaggleCutlineConfig:
    username: str
    key: str
    dataset_ref: str
    kernel_ref: str
    work_dir: Path
    poll_seconds: int = DEFAULT_POLL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def run_kaggle_cutline_debug(
    *,
    request_payload: dict[str, Any],
    page_image_path: Path,
    request_dir: Path,
) -> dict[str, Any]:
    """Submit one rendered page to Kaggle and return cutline_result.json."""

    config = _load_config()
    _ensure_kaggle_cli(config)

    if not page_image_path.exists():
        raise FileNotFoundError(f"Rendered page image was not found: {page_image_path}")

    request_id = str(request_payload.get("request_id") or "").strip()
    if not request_id:
        raise KaggleCutlineDebugError("request_payload is missing request_id.")

    dataset_dir = request_dir / "dataset"
    kernel_dir = request_dir / "kernel"
    download_dir = request_dir / "download"
    _prepare_dataset(
        dataset_dir=dataset_dir,
        dataset_ref=config.dataset_ref,
        request_payload=request_payload,
        page_image_path=page_image_path,
    )
    _prepare_kernel(
        kernel_dir=kernel_dir,
        kernel_ref=config.kernel_ref,
        dataset_ref=config.dataset_ref,
    )

    _publish_dataset(config=config, dataset_dir=dataset_dir, request_id=request_id)
    _push_kernel(config=config, kernel_dir=kernel_dir)
    _wait_kernel_complete(config=config)
    _download_kernel_output(config=config, download_dir=download_dir)

    status = _read_status(download_dir=download_dir, request_id=request_id)
    if status and status.get("request_id") != request_id:
        raise KaggleCutlineDebugError(
            "Downloaded Kaggle status belongs to a different request_id."
        )
    if status and status.get("status") == "failed":
        raise KaggleCutlineDebugError(
            f"Kaggle cutline kernel failed: {status.get('error') or status}"
        )

    result_path = download_dir / "cutline_result.json"
    if not result_path.exists():
        raise KaggleCutlineDebugError(
            f"Kaggle cutline output was not found: {result_path}"
        )

    result = read_json(result_path)
    if not isinstance(result, dict):
        raise KaggleCutlineDebugError(f"Kaggle result JSON must be an object: {result_path}")

    if result.get("request_id") != request_id:
        raise KaggleCutlineDebugError(
            "Downloaded Kaggle cutline_result.json belongs to a different request_id."
        )

    result["_kaggle_output_dir"] = str(download_dir)
    return result


def run_kaggle_cutline_batch(
    *,
    request_payload: dict[str, Any],
    page_image_paths: dict[str, Path],
    request_dir: Path,
) -> dict[str, Any]:
    """Submit many rendered cutline pages to Kaggle in one kernel run."""

    config = _load_config()
    _ensure_kaggle_cli(config)

    request_id = str(request_payload.get("request_id") or "").strip()
    if not request_id:
        raise KaggleCutlineDebugError("request_payload is missing request_id.")

    items = request_payload.get("items")
    if not isinstance(items, list) or not items:
        raise KaggleCutlineDebugError("request_payload must include non-empty items.")

    for chunk_name, page_image_path in page_image_paths.items():
        if not page_image_path.exists():
            raise FileNotFoundError(
                f"Rendered page image for {chunk_name} was not found: {page_image_path}"
            )

    dataset_dir = request_dir / "dataset"
    kernel_dir = request_dir / "kernel"
    download_dir = request_dir / "download"
    _prepare_batch_dataset(
        dataset_dir=dataset_dir,
        dataset_ref=config.dataset_ref,
        request_payload=request_payload,
        page_image_paths=page_image_paths,
    )
    _prepare_kernel(
        kernel_dir=kernel_dir,
        kernel_ref=config.kernel_ref,
        dataset_ref=config.dataset_ref,
    )

    _publish_dataset(config=config, dataset_dir=dataset_dir, request_id=request_id)
    _push_kernel(config=config, kernel_dir=kernel_dir)
    _wait_kernel_complete(config=config)
    _download_kernel_output(config=config, download_dir=download_dir)

    status = _read_status(download_dir=download_dir, request_id=request_id)
    if status and status.get("request_id") != request_id:
        raise KaggleCutlineDebugError(
            "Downloaded Kaggle status belongs to a different request_id."
        )
    if status and status.get("status") == "failed":
        raise KaggleCutlineDebugError(
            f"Kaggle cutline kernel failed: {status.get('error') or status}"
        )

    results_path = download_dir / "cutline_results.json"
    if not results_path.exists():
        raise KaggleCutlineDebugError(
            f"Kaggle batch cutline output was not found: {results_path}"
        )

    result = read_json(results_path)
    if not isinstance(result, dict):
        raise KaggleCutlineDebugError(
            f"Kaggle batch result JSON must be an object: {results_path}"
        )
    if result.get("request_id") != request_id:
        raise KaggleCutlineDebugError(
            "Downloaded Kaggle cutline_results.json belongs to a different request_id."
        )

    result["_kaggle_output_dir"] = str(download_dir)
    return result


def check_kaggle_cutline_readiness() -> dict[str, Any]:
    _load_local_env()
    missing_env = _missing_required_env()
    kernel_script_exists = (KERNEL_SOURCE_DIR / "script.py").exists()
    kaggle_cli_available = shutil.which("kaggle") is not None

    notes: list[str] = []
    if missing_env:
        notes.append("Missing required Kaggle configuration.")
    if not kernel_script_exists:
        notes.append(f"Missing kernel script: {KERNEL_SOURCE_DIR / 'script.py'}")
    if not kaggle_cli_available:
        notes.append("Kaggle CLI is not available on PATH.")

    ready = not missing_env and kernel_script_exists and kaggle_cli_available
    return {
        "ready": ready,
        "missing_env": missing_env,
        "kernel_script_exists": kernel_script_exists,
        "kaggle_cli_available": kaggle_cli_available,
        "required_env": REQUIRED_ENV_KEYS,
        "optional_env": [
            "AI_EXTRACT_KAGGLE_WORK_DIR",
            "AI_EXTRACT_KAGGLE_POLL_SECONDS",
            "AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS",
        ],
        "notes": notes,
    }


def prepare_kaggle_cutline_debug_package(
    *,
    request_payload: dict[str, Any],
    page_image_path: Path,
    request_dir: Path,
) -> dict[str, str]:
    """Build the local one-page Kaggle package without submitting it."""

    _load_local_env()
    config = _load_config(validate_cli=False)
    dataset_dir = request_dir / "dataset"
    kernel_dir = request_dir / "kernel"
    _prepare_dataset(
        dataset_dir=dataset_dir,
        dataset_ref=config.dataset_ref,
        request_payload=request_payload,
        page_image_path=page_image_path,
    )
    _prepare_kernel(
        kernel_dir=kernel_dir,
        kernel_ref=config.kernel_ref,
        dataset_ref=config.dataset_ref,
    )
    return {
        "dataset_dir": str(dataset_dir),
        "kernel_dir": str(kernel_dir),
        "run_request_path": str(dataset_dir / "run_request.json"),
        "page_image_path": str(dataset_dir / "page.png"),
    }


def _load_config(*, validate_cli: bool = True) -> KaggleCutlineConfig:
    del validate_cli
    _load_local_env()
    username = os.getenv("AI_EXTRACT_KAGGLE_USERNAME")
    key = os.getenv("AI_EXTRACT_KAGGLE_KEY")
    dataset_slug = os.getenv("AI_EXTRACT_KAGGLE_DATASET_SLUG", "").strip()
    kernel_ref = os.getenv("AI_EXTRACT_KAGGLE_KERNEL_REF", "").strip()
    work_dir = Path(os.getenv("AI_EXTRACT_KAGGLE_WORK_DIR", str(DEFAULT_WORK_DIR)))
    poll_seconds = int(os.getenv("AI_EXTRACT_KAGGLE_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    timeout_seconds = int(os.getenv("AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))

    missing = _missing_required_env()
    if missing:
        raise KaggleCutlineDebugNotConfigured(
            "Kaggle cutline debug is not configured. Missing required "
            f"variables: {', '.join(missing)}."
        )

    dataset_ref = dataset_slug if "/" in dataset_slug else f"{username}/{dataset_slug}"
    return KaggleCutlineConfig(
        username=username,
        key=key,
        dataset_ref=dataset_ref,
        kernel_ref=kernel_ref,
        work_dir=work_dir,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
    )


def _load_local_env() -> None:
    load_dotenv(CORE_DIR / "config.env")


def _missing_required_env() -> list[str]:
    missing: list[str] = []
    if not os.getenv("AI_EXTRACT_KAGGLE_USERNAME"):
        missing.append("AI_EXTRACT_KAGGLE_USERNAME")
    if not os.getenv("AI_EXTRACT_KAGGLE_KEY"):
        missing.append("AI_EXTRACT_KAGGLE_KEY")
    if not os.getenv("AI_EXTRACT_KAGGLE_DATASET_SLUG"):
        missing.append("AI_EXTRACT_KAGGLE_DATASET_SLUG")
    if not os.getenv("AI_EXTRACT_KAGGLE_KERNEL_REF"):
        missing.append("AI_EXTRACT_KAGGLE_KERNEL_REF")
    return missing


def _kaggle_env(config: KaggleCutlineConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = config.username
    env["KAGGLE_KEY"] = config.key
    return env


def _run_kaggle_command(
    config: KaggleCutlineConfig,
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=_kaggle_env(config),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise KaggleCutlineDebugError(
            "Kaggle command failed "
            f"(exit={completed.returncode}, cmd={' '.join(command)}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


def _ensure_kaggle_cli(config: KaggleCutlineConfig) -> None:
    if shutil.which("kaggle") is None:
        raise KaggleCutlineDebugNotConfigured(
            "Kaggle CLI is not installed. Install the kaggle package and configure "
            "AI_EXTRACT_KAGGLE_* settings."
        )
    _run_kaggle_command(config, ["kaggle", "--version"])


def _prepare_dataset(
    *,
    dataset_dir: Path,
    dataset_ref: str,
    request_payload: dict[str, Any],
    page_image_path: Path,
) -> None:
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(page_image_path, dataset_dir / "page.png")
    write_json(dataset_dir / "run_request.json", request_payload)
    write_json(
        dataset_dir / "dataset-metadata.json",
        {
            "title": dataset_ref.split("/", 1)[1],
            "id": dataset_ref,
            "licenses": [{"name": "CC0-1.0"}],
        },
    )


def _prepare_batch_dataset(
    *,
    dataset_dir: Path,
    dataset_ref: str,
    request_payload: dict[str, Any],
    page_image_paths: dict[str, Path],
) -> None:
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    pages_dir = dataset_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    for chunk_name, page_image_path in page_image_paths.items():
        shutil.copyfile(page_image_path, pages_dir / f"{chunk_name}.png")

    write_json(dataset_dir / "run_request.json", request_payload)
    write_json(
        dataset_dir / "dataset-metadata.json",
        {
            "title": dataset_ref.split("/", 1)[1],
            "id": dataset_ref,
            "licenses": [{"name": "CC0-1.0"}],
        },
    )


def _prepare_kernel(
    *,
    kernel_dir: Path,
    kernel_ref: str,
    dataset_ref: str,
) -> None:
    if kernel_dir.exists():
        shutil.rmtree(kernel_dir)
    kernel_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_SOURCE_DIR / "script.py", kernel_dir / "script.py")
    write_json(
        kernel_dir / "kernel-metadata.json",
        {
            "id": kernel_ref,
            "title": kernel_ref.split("/", 1)[1],
            "code_file": "script.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": False,
            "enable_internet": True,
            "dataset_sources": [dataset_ref],
            "competition_sources": [],
        },
    )


def _publish_dataset(
    *,
    config: KaggleCutlineConfig,
    dataset_dir: Path,
    request_id: str,
) -> None:
    version = _run_kaggle_command(
        config,
        [
            "kaggle",
            "datasets",
            "version",
            "-p",
            str(dataset_dir),
            "-m",
            f"AI-Extract cutline debug {request_id}",
            "--dir-mode",
            "zip",
        ],
        check=False,
    )
    if version.returncode == 0:
        return

    create = _run_kaggle_command(
        config,
        [
            "kaggle",
            "datasets",
            "create",
            "-p",
            str(dataset_dir),
            "--dir-mode",
            "zip",
        ],
        check=False,
    )
    if create.returncode != 0:
        raise KaggleCutlineDebugError(
            "Failed to create/version Kaggle dataset. "
            f"version_error={version.stderr.strip() or version.stdout.strip()} "
            f"create_error={create.stderr.strip() or create.stdout.strip()}"
        )


def _push_kernel(*, config: KaggleCutlineConfig, kernel_dir: Path) -> None:
    _run_kaggle_command(
        config,
        ["kaggle", "kernels", "push", "-p", str(kernel_dir)],
    )


def _wait_kernel_complete(config: KaggleCutlineConfig) -> None:
    started = time.monotonic()
    while True:
        status = _run_kaggle_command(
            config,
            ["kaggle", "kernels", "status", config.kernel_ref],
        ).stdout.strip()

        if "KernelWorkerStatus.COMPLETE" in status:
            return
        if "KernelWorkerStatus.FAILED" in status or "KernelWorkerStatus.ERROR" in status:
            raise KaggleCutlineDebugError(f"Kaggle kernel failed: {status}")
        if time.monotonic() - started > config.timeout_seconds:
            raise KaggleCutlineDebugError(
                f"Timed out waiting for Kaggle kernel: {config.kernel_ref}"
            )

        time.sleep(config.poll_seconds)


def _download_kernel_output(
    *,
    config: KaggleCutlineConfig,
    download_dir: Path,
) -> None:
    if download_dir.exists():
        shutil.rmtree(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    _run_kaggle_command(
        config,
        [
            "kaggle",
            "kernels",
            "output",
            config.kernel_ref,
            "-p",
            str(download_dir),
            "--force",
        ],
    )


def _read_status(download_dir: Path, request_id: str) -> dict[str, Any] | None:
    candidates = [
        download_dir / f"current_run_status_{request_id}.json",
        download_dir / "current_run_status.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        payload = read_json(candidate)
        if isinstance(payload, dict):
            return payload
    return None
