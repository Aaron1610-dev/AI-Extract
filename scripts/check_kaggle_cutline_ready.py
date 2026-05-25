from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
KERNEL_SCRIPT = APP_DIR / "pipeline" / "kaggle_kernels" / "debug-cutline-one-chunk" / "script.py"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
CONFIG_ENV = APP_DIR / "core" / "config.env"


REQUIRED_ENV = [
    "AI_EXTRACT_KAGGLE_USERNAME",
    "AI_EXTRACT_KAGGLE_KEY",
    "AI_EXTRACT_KAGGLE_DATASET_SLUG",
    "AI_EXTRACT_KAGGLE_KERNEL_REF",
]
REQUIRED_REQUIREMENTS = ["kaggle", "PyMuPDF"]


def main() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    _load_config_env()

    report = _build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _load_config_env() -> None:
    if not CONFIG_ENV.exists():
        return

    for raw_line in CONFIG_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _build_report() -> dict:
    missing_env = [name for name in REQUIRED_ENV if not os.getenv(name)]
    backend_uses_local_paddleocr = _backend_uses_local_paddleocr()
    legacy_placeholder = "AI_EXTRACT_KAGGLE_" + "CUTLINE_COMMAND"
    uses_external_command_placeholder = _contains_text(APP_DIR, legacy_placeholder)
    requirements_status = _requirements_status()

    notes: list[str] = []
    for name in missing_env:
        notes.append(f"Missing {name}")
    if not KERNEL_SCRIPT.exists():
        notes.append(f"Missing kernel script: {KERNEL_SCRIPT}")
    if backend_uses_local_paddleocr:
        notes.append("Backend app code appears to import/call local PaddleOCR.")
    if uses_external_command_placeholder:
        notes.append("Old external command placeholder is still referenced in app code.")
    if not requirements_status["ok"]:
        missing = ", ".join(requirements_status["missing"])
        notes.append(f"Missing backend requirements: {missing}")

    ready = (
        not missing_env
        and KERNEL_SCRIPT.exists()
        and not backend_uses_local_paddleocr
        and not uses_external_command_placeholder
        and requirements_status["ok"]
    )

    return {
        "ready": ready,
        "missing_env": missing_env,
        "kernel_script_exists": KERNEL_SCRIPT.exists(),
        "backend_uses_local_paddleocr": backend_uses_local_paddleocr,
        "uses_external_command_placeholder": uses_external_command_placeholder,
        "requirements_ok": requirements_status["ok"],
        "requirements_missing": requirements_status["missing"],
        "notes": notes,
    }


def _backend_uses_local_paddleocr() -> bool:
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "kaggle_kernels" in path.parts:
            continue

        text = path.read_text(encoding="utf-8")
        if "from paddleocr import" in text or "PaddleOCR(" in text:
            return True

    return False


def _contains_text(root: Path, needle: str) -> bool:
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if needle in path.read_text(encoding="utf-8"):
            return True
    return False


def _requirements_status() -> dict:
    if not REQUIREMENTS.exists():
        return {"ok": False, "missing": REQUIRED_REQUIREMENTS}

    lines = [
        line.strip().split("==", 1)[0].lower()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    installed = set(lines)
    missing = [
        requirement
        for requirement in REQUIRED_REQUIREMENTS
        if requirement.lower() not in installed
    ]
    paddle_deps = {"paddleocr", "paddlepaddle"}
    missing.extend(sorted(name for name in paddle_deps if name in installed))

    return {"ok": not missing, "missing": missing}


if __name__ == "__main__":
    main()
