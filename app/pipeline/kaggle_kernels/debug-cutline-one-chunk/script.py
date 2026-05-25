from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path


os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


WORKING_DIR = Path("/kaggle/working")
STATUS_FILE = WORKING_DIR / "current_run_status.json"


def sh(command: str) -> None:
    print(">>>", command, flush=True)
    subprocess.run(command, shell=True, check=True)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(request_id: str, status: str, **extra) -> None:
    payload = {"request_id": request_id, "status": status}
    payload.update(extra)
    write_json(STATUS_FILE, payload)
    write_json(WORKING_DIR / f"current_run_status_{request_id}.json", payload)


def find_input_file(name: str) -> Path:
    matches = sorted(Path("/kaggle/input").rglob(name))
    if not matches:
        raise FileNotFoundError(f"Missing Kaggle input file: {name}")
    return matches[0]


def load_request() -> dict:
    request_path = find_input_file("run_request.json")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("run_request.json must contain a JSON object")
    return payload


def poly_bbox(poly) -> list[float]:
    import numpy as np

    points = np.array(poly, dtype=np.float32).reshape(-1, 2)
    return [
        float(np.min(points[:, 0])),
        float(np.min(points[:, 1])),
        float(np.max(points[:, 0])),
        float(np.max(points[:, 1])),
    ]


def parse_ocr_result(result) -> list[dict]:
    out = []
    if result is None:
        return out
    if not isinstance(result, list):
        result = [result]

    for page in result:
        if not isinstance(page, list):
            continue
        for det in page:
            if not (isinstance(det, (list, tuple)) and len(det) >= 2):
                continue
            text_score = det[1]
            if not (
                isinstance(text_score, (list, tuple))
                and len(text_score) >= 2
            ):
                continue
            text = str(text_score[0] or "").strip()
            if not text:
                continue
            out.append(
                {
                    "text": text,
                    "bbox": poly_bbox(det[0]),
                    "score": float(text_score[1] or 0.0),
                }
            )
    return out


def group_to_lines(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    heights = [item["bbox"][3] - item["bbox"][1] for item in candidates]
    median_height = sorted(heights)[len(heights) // 2]
    y_tolerance = max(10.0, median_height * 0.65)
    sorted_items = sorted(
        candidates,
        key=lambda item: ((item["bbox"][1] + item["bbox"][3]) * 0.5, item["bbox"][0]),
    )
    groups = []

    for item in sorted_items:
        y_center = (item["bbox"][1] + item["bbox"][3]) * 0.5
        for group in groups:
            if abs(y_center - group["y_ref"]) <= y_tolerance:
                group["items"].append(item)
                count = len(group["items"])
                group["y_ref"] = (group["y_ref"] * (count - 1) + y_center) / count
                break
        else:
            groups.append({"y_ref": y_center, "items": [item]})

    lines = []
    for group in groups:
        items = sorted(group["items"], key=lambda item: item["bbox"][0])
        bbox = [
            min(item["bbox"][0] for item in items),
            min(item["bbox"][1] for item in items),
            max(item["bbox"][2] for item in items),
            max(item["bbox"][3] for item in items),
        ]
        lines.append(
            {
                "text": " ".join(item["text"] for item in items).strip(),
                "bbox": bbox,
                "score": max(float(item.get("score") or 0.0) for item in items),
            }
        )
    return sorted(lines, key=lambda line: (line["bbox"][1], line["bbox"][0]))


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^\w\s.]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def title_score(observed: str, expected: str) -> int:
    if not observed or not expected:
        return 0
    if expected in observed:
        return max(3, len(expected.split()))
    words = [word for word in expected.split() if len(word) > 1]
    return sum(1 for word in words if word in observed)


def merge_lines(lines: list[dict], index: int, look_ahead: int = 2) -> dict:
    selected = lines[index : index + look_ahead + 1]
    bbox = [
        min(line["bbox"][0] for line in selected),
        min(line["bbox"][1] for line in selected),
        max(line["bbox"][2] for line in selected),
        max(line["bbox"][3] for line in selected),
    ]
    return {
        "text": " ".join(line["text"] for line in selected).strip(),
        "bbox": bbox,
        "score": max(float(line.get("score") or 0.0) for line in selected),
    }


def find_best_match(lines: list[dict], heading: str, title: str) -> dict | None:
    heading_number_match = re.search(r"\d+", heading or "")
    heading_number = heading_number_match.group(0) if heading_number_match else ""
    heading_norm = normalize_text(heading)
    title_norm = normalize_text(title)
    best = None

    for index, line in enumerate(lines):
        line_norm = normalize_text(line["text"])
        starts_heading = bool(heading_number) and re.match(
            rf"^\s*{re.escape(heading_number)}\s*\.?",
            line_norm,
        )
        contains_heading = bool(heading_norm) and heading_norm in line_norm
        score_title = title_score(line_norm, title_norm)
        score = score_title + (4 if starts_heading else 0) + (2 if contains_heading else 0)
        match_line = dict(line)
        mode = "prefix_line" if starts_heading else "contains_heading"

        if starts_heading and score_title < 2:
            merged = merge_lines(lines, index)
            merged_norm = normalize_text(merged["text"])
            merged_score_title = title_score(merged_norm, title_norm)
            merged_score = merged_score_title + 4 + (
                2 if heading_norm and heading_norm in merged_norm else 0
            )
            if merged_score > score:
                score = merged_score
                score_title = merged_score_title
                match_line = merged
                mode = "merge_next"

        if not (starts_heading or contains_heading):
            continue
        if score_title < 1 and score < 6:
            continue

        candidate = {**match_line, "mode": mode, "match_score": int(score)}
        if best is None or candidate["match_score"] > best["match_score"]:
            best = candidate

    return best


def draw_bbox(page_path: Path, output_path: Path, match: dict | None, lines: list[dict]) -> None:
    import cv2

    image = cv2.imread(str(page_path))
    if image is None:
        return
    height, width = image.shape[:2]
    for line in lines:
        x0, y0, x1, y1 = [int(round(v)) for v in line["bbox"]]
        cv2.rectangle(image, (max(0, x0), max(0, y0)), (min(width - 1, x1), min(height - 1, y1)), (0, 180, 255), 1)
    if match:
        x0, y0, x1, y1 = [int(round(v)) for v in match["bbox"]]
        cv2.line(image, (0, max(0, y0)), (width - 1, max(0, y0)), (0, 0, 255), 3)
        cv2.rectangle(image, (max(0, x0), max(0, y0)), (min(width - 1, x1), min(height - 1, y1)), (0, 255, 0), 2)
    cv2.imwrite(str(output_path), image)


def main() -> None:
    sh("python -m pip -q install --upgrade pip")
    sh("python -m pip -q install paddlepaddle==3.3.0")
    sh("python -m pip -q uninstall -y paddleocr paddlex || true")
    sh("python -m pip -q install --no-deps paddleocr==2.7.3")
    sh("python -m pip -q install opencv-python-headless pyclipper shapely imgaug pillow tqdm lmdb attrdict fire rapidfuzz visualdl")

    import cv2
    import numpy as np

    if not hasattr(np, "sctypes"):
        np.sctypes = {
            "int": [np.int8, np.int16, np.int32, np.int64],
            "uint": [np.uint8, np.uint16, np.uint32, np.uint64],
            "float": [np.float16, np.float32, np.float64],
            "complex": [np.complex64, np.complex128],
            "others": [np.bool_, np.bytes_, np.str_, np.void],
        }

    run_request = load_request()
    request_id = str(run_request.get("request_id") or "unknown")
    write_status(request_id, "started")

    page_path = find_input_file("page.png")
    image = cv2.imread(str(page_path))
    if image is None:
        raise RuntimeError(f"Could not read page image: {page_path}")

    module = __import__("paddleocr", fromlist=["Paddle" + "OCR"])
    ocr_class = getattr(module, "Paddle" + "OCR")
    try:
        ocr = ocr_class(
            lang="vi",
            use_textline_orientation=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            text_det_limit_type="max",
            text_det_limit_side_len=4096,
        )
    except Exception:
        ocr = ocr_class(lang="vi", det_limit_type="max", det_limit_side_len=4096)

    result = ocr.ocr(image, cls=False)
    candidates = parse_ocr_result(result)
    lines = group_to_lines(candidates)
    match = find_best_match(
        lines,
        heading=str(run_request.get("heading") or ""),
        title=str(run_request.get("title") or ""),
    )

    bbox_path = WORKING_DIR / "bbox.png"
    draw_bbox(page_path, bbox_path, match, lines)

    payload = {
        "request_id": request_id,
        "matched": bool(match),
        "matched_text": match["text"] if match else None,
        "bbox": [int(round(v)) for v in match["bbox"]] if match else None,
        "y_cut": int(round(match["bbox"][1])) if match else None,
        "reason": None if match else "No matching OCR box found",
        "ocr_candidates": [
            {
                "text": line["text"],
                "bbox": [int(round(v)) for v in line["bbox"]],
                "score": float(line.get("score") or 0.0),
            }
            for line in lines
        ],
    }
    write_json(WORKING_DIR / "cutline_result.json", payload)
    write_status(request_id, "completed", matched=bool(match))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        request_id = "unknown"
        try:
            request_id = str(load_request().get("request_id") or "unknown")
        except Exception:
            pass
        write_status(request_id, "failed", error=str(exc))
        raise
