from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any


os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

WORKING_DIR = Path("/kaggle/working")
STATUS_FILE = WORKING_DIR / "current_run_status.json"

MIN_MATCH_REQUIRED = 3
ALLOW_WEAK_CUT = True
WEAK_MIN_LCS = 2
WEAK_COV_EXP = 0.65
WEAK_COV_OBS = 0.80
WEAK_MIN_OBS = 3
WEAK_ALLOWED_MODES = {"prefix_line", "heading_left_title", "same_line", "merge_next"}
FORCE_CUT_ON_MODES = {"prefix_line"}


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


def find_input_path(relative_path: str) -> Path:
    normalized = relative_path.strip().lstrip("/")
    matches = sorted(Path("/kaggle/input").rglob(normalized))
    if matches:
        return matches[0]
    return find_input_file(Path(normalized).name)


def load_request() -> dict:
    request_path = find_input_file("run_request.json")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("run_request.json must contain a JSON object")
    return payload


def poly_bbox(poly: Any) -> list[float]:
    import numpy as np

    points = np.array(poly, dtype=np.float32).reshape(-1, 2)
    return [
        float(np.min(points[:, 0])),
        float(np.min(points[:, 1])),
        float(np.max(points[:, 0])),
        float(np.max(points[:, 1])),
    ]


def parse_ocr_result(result: Any) -> list[dict]:
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
                "items": items,
            }
        )
    return sorted(lines, key=lambda line: (line["bbox"][1], line["bbox"][0]))


def _score(m: int, has_heading: bool, has_dot: bool) -> int:
    return m * 10 + (2 if has_heading else 0) + (1 if has_dot else 0)


def _heading_label_pattern(heading_label: str) -> str:
    return re.escape(heading_label)


def _is_pure_heading_token(text: str, heading_label: str) -> tuple[bool, bool]:
    raw = (text or "").strip()
    label = _heading_label_pattern(heading_label)
    if re.match(rf"^\s*{label}\s*\)\s*$", raw):
        return False, False
    match = re.match(rf"^\s*{label}\s*(\.)?\s*$", raw)
    if not match:
        return False, False
    return True, bool(match.group(1))


def _has_dot_heading(text: str, heading_label: str) -> bool:
    label = _heading_label_pattern(heading_label)
    return bool(re.search(rf"^\s*{label}\s*\.", text or ""))


def _v_overlap_ratio(a_y0: float, a_y1: float, b_y0: float, b_y1: float) -> float:
    inter = max(0.0, min(a_y1, b_y1) - max(a_y0, b_y0))
    denom = max(1.0, min(a_y1 - a_y0, b_y1 - b_y0))
    return inter / denom


def collect_heading_candidates(dets: list[dict], heading_label: str) -> list[dict]:
    out = []
    for det in dets:
        ok, has_dot = _is_pure_heading_token(det.get("text", ""), heading_label)
        if ok:
            item = dict(det)
            item["has_dot"] = has_dot
            out.append(item)
    return out


def find_heading_left_for_line(
    heading_cands: list[dict],
    line: dict,
    *,
    x_gap_max: float = 220.0,
    min_v_overlap: float = 0.25,
) -> dict | None:
    best = None
    lx0, ly0, _, ly1 = line["bbox"]
    for heading in heading_cands:
        hx0, hy0, hx1, hy1 = heading["bbox"]
        del hx0
        if float(hx1) > float(lx0) + 20:
            continue
        gap = float(lx0) - float(hx1)
        if gap < 0 or gap > x_gap_max:
            continue
        overlap = _v_overlap_ratio(float(hy0), float(hy1), float(ly0), float(ly1))
        if overlap < min_v_overlap:
            continue
        key = (gap, -overlap)
        if best is None or key < best[0]:
            best = (key, heading)
    return best[1] if best else None


def remove_diacritics_char_no_case_change(ch: str) -> str | None:
    if not ch:
        return None
    if ch == "Đ":
        return "D"
    if ch == "đ":
        return None
    if (not ch.isalpha()) or (not ch.isupper()):
        return None
    base = unicodedata.normalize("NFD", ch)
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    if len(base) != 1 or (not base.isalpha()) or (not base.isupper()):
        return None
    return base


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"[0-9]+|[A-Za-zÀ-Ỵà-ỵĐđ]+", text or "")


def build_expected_letters_from_title(title: str) -> list[str]:
    out = []
    for word in re.split(r"\s+", (title or "").strip()):
        if not word:
            continue
        first_alpha = None
        for ch in word:
            if ch.isalpha():
                first_alpha = ch
                break
        if not first_alpha:
            continue
        base = remove_diacritics_char_no_case_change(first_alpha)
        if base:
            out.append(base)
    return out


def extract_initials_no_case_change(text: str) -> list[str]:
    initials = []
    for token in tokenize_words(text):
        if token.isdigit():
            continue
        base = remove_diacritics_char_no_case_change(token[0])
        if base:
            initials.append(base)
    return initials


def prefix_match_count(observed: list[str], expected: list[str]) -> int:
    n = min(len(observed), len(expected))
    count = 0
    for index in range(n):
        if observed[index] == expected[index]:
            count += 1
        else:
            break
    return count


def robust_match_count(observed: list[str], expected: list[str]) -> int:
    prefix = prefix_match_count(observed, expected)
    anchor = 2 if len(expected) <= 4 else 3
    if prefix < min(anchor, len(expected)):
        robust = prefix
    else:
        j = prefix
        for ch in observed[prefix:]:
            if j < len(expected) and ch == expected[j]:
                j += 1
        robust = j

    if len(expected) >= 6:
        threshold = (8 * len(expected) + 9) // 10
        begin_ok = (len(expected) == 0) or (expected[0] in observed[:3])
        if begin_ok:
            lcs = lcs_len(expected, observed)
            if lcs >= threshold:
                return lcs
    return robust


def lcs_len(a: list[str], b: list[str]) -> int:
    dp = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        prev = 0
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            cur = dp[j]
            if ai == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j - 1])
            prev = cur
    return dp[len(b)]


def split_heading_prefix(raw_text: str, heading_label: str, require_dot: bool = False) -> tuple[bool, str]:
    text = (raw_text or "").strip()
    label = _heading_label_pattern(heading_label)
    if re.match(rf"^\s*{label}\s*\)", text):
        return False, ""
    if require_dot:
        match = re.match(rf"^\s*{label}\s*\.\s*(\S.+)$", text)
    else:
        match = re.match(rf"^\s*{label}\s*\.?\s*(\S.+)$", text)
    if not match:
        return False, ""
    remaining = match.group(1).strip()
    if remaining and not remaining[0].isdigit():
        return True, remaining
    return False, ""


def build_seq_from_line_items(items: list[dict], heading_label: str) -> tuple[list[str] | None, dict | None, bool]:
    heading_tokens = tokenize_words(heading_label)
    if len(heading_tokens) != 1:
        return None, None, False
    expected_heading_token = heading_tokens[0]
    started = False
    seq = []
    hbbox = None
    has_dot = False
    for item in sorted(items, key=lambda det: det["bbox"][0]):
        tokens = tokenize_words(item.get("text", ""))
        if not tokens:
            continue
        if not started:
            for index, token in enumerate(tokens):
                if token == expected_heading_token:
                    started = True
                    seq.append(expected_heading_token)
                    x0, y0, x1, y1 = item["bbox"]
                    hbbox = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
                    has_dot = _has_dot_heading(item.get("text", ""), heading_label)
                    for token2 in tokens[index + 1:]:
                        if token2.isdigit():
                            continue
                        base = remove_diacritics_char_no_case_change(token2[0])
                        if base:
                            seq.append(base)
                    break
            continue
        for token in tokens:
            if token.isdigit():
                continue
            base = remove_diacritics_char_no_case_change(token[0])
            if base:
                seq.append(base)
    if not started:
        return None, None, False
    return seq, hbbox, has_dot


def try_merge_title_from_next_lines(
    lines: list[dict],
    idx: int,
    hbbox: dict,
    expected_letters: list[str],
    look_ahead: int = 3,
) -> tuple[int, list[str]]:
    best_m = 0
    best_obs = []
    hx1 = hbbox["x1"]
    hmid = 0.5 * (hbbox["y0"] + hbbox["y1"])
    h_h = max(1.0, hbbox["y1"] - hbbox["y0"])

    for j in range(idx + 1, min(len(lines), idx + look_ahead + 1)):
        line2 = lines[j]
        x0, y0, _, y1 = line2["bbox"]
        if float(x0) < hx1 - 30:
            continue
        mid2 = 0.5 * (float(y0) + float(y1))
        if abs(mid2 - hmid) > max(60.0, h_h * 2.5):
            continue
        obs2 = extract_initials_no_case_change(line2["text"])
        m2 = robust_match_count(obs2, expected_letters)
        if m2 > best_m:
            best_m = m2
            best_obs = obs2
        if best_m >= len(expected_letters):
            break
    return best_m, best_obs


def extract_heading_label(heading: str) -> str | None:
    match = re.match(r"^\s*(\d+|[IVXLCDM]+)\s*\.\s*$", heading or "")
    return match.group(1) if match else None


def bbox_ints(item: dict) -> list[int]:
    return [int(round(v)) for v in item["bbox"]]


def merge_line_records(lines: list[dict], first: dict, extra_obs: list[str]) -> dict:
    # Keep the heading bbox as the cutline anchor, but expose merged text for debug.
    merged_text = first["text"]
    if extra_obs:
        merged_text = " ".join([merged_text] + [line["text"] for line in lines])
    out = dict(first)
    out["text"] = merged_text
    return out


def match_heading_title(lines: list[dict], dets: list[dict], heading: str, title: str) -> dict:
    heading_label = extract_heading_label(heading)
    expected_letters = build_expected_letters_from_title(title)
    if heading_label is None:
        return build_no_match_payload(
            reason="missing_heading_label",
            lines=lines,
            expected_letters=expected_letters,
            best=None,
            early_stop=False,
        )
    if not expected_letters:
        return build_no_match_payload(
            reason="missing_expected_title_letters",
            lines=lines,
            expected_letters=expected_letters,
            best=None,
            early_stop=False,
        )

    heading_cands = collect_heading_candidates(dets, heading_label)
    best = None
    early_stop = False

    for index, line in enumerate(lines):
        items = line.get("items", [])
        obs_title = extract_initials_no_case_change(line["text"])
        matched_title = robust_match_count(obs_title, expected_letters)
        cand_list = []

        has_pref, remaining = split_heading_prefix(line["text"], heading_label, require_dot=False)
        if has_pref:
            obs_pref = extract_initials_no_case_change(remaining)
            matched_pref = robust_match_count(obs_pref, expected_letters)
            has_dot_pref = _has_dot_heading(line["text"], heading_label)
            cand_list.append(
                make_candidate(
                    line=line,
                    matched=matched_pref,
                    observed=obs_pref,
                    mode="prefix_line",
                    has_heading=True,
                    has_dot=has_dot_pref,
                )
            )

        h_left = find_heading_left_for_line(heading_cands, line)
        if h_left is not None:
            cand_list.append(
                make_candidate(
                    line=line,
                    matched=matched_title,
                    observed=obs_title,
                    mode="heading_left_title",
                    has_heading=True,
                    has_dot=bool(h_left.get("has_dot", False)),
                )
            )

        seq, hbbox, has_dot = build_seq_from_line_items(items, heading_label)
        if seq is not None and hbbox is not None:
            obs_same = seq[1:]
            matched_same = robust_match_count(obs_same, expected_letters)
            cand_list.append(
                make_candidate(
                    line=line,
                    matched=matched_same,
                    observed=obs_same,
                    mode="same_line",
                    has_heading=True,
                    has_dot=has_dot,
                )
            )
            if matched_same < len(expected_letters):
                m2, obs2 = try_merge_title_from_next_lines(lines, index, hbbox, expected_letters)
                matched_merge_comb = robust_match_count(obs_same + obs2, expected_letters) if obs2 else m2
                if matched_merge_comb >= m2:
                    matched_merge = matched_merge_comb
                    obs_merge = obs_same + obs2
                else:
                    matched_merge = m2
                    obs_merge = obs2
                cand_list.append(
                    make_candidate(
                        line=line,
                        matched=matched_merge,
                        observed=obs_merge,
                        mode="merge_next",
                        has_heading=True,
                        has_dot=has_dot,
                    )
                )

        if not cand_list:
            continue

        cand_list.sort(key=lambda item: item["match_score"], reverse=True)
        current = cand_list[0]
        if best is None or current["match_score"] > best["match_score"]:
            best = current

        if current["matched_prefix"] >= len(expected_letters):
            early_stop = True
            break

    if best is None:
        return build_no_match_payload(
            reason="no_heading_title_candidate",
            lines=lines,
            expected_letters=expected_letters,
            best=None,
            early_stop=early_stop,
        )

    return finalize_match(best=best, lines=lines, expected_letters=expected_letters, early_stop=early_stop)


def make_candidate(
    *,
    line: dict,
    matched: int,
    observed: list[str],
    mode: str,
    has_heading: bool,
    has_dot: bool,
) -> dict:
    match_score = _score(matched, has_heading, has_dot)
    lcs = lcs_len(observed, [])
    del lcs
    return {
        **line,
        "matched_prefix": int(matched),
        "observed_initials": observed,
        "best_mode": mode,
        "mode": mode,
        "has_heading": bool(has_heading),
        "has_dot": bool(has_dot),
        "match_score": int(match_score),
    }


def finalize_match(best: dict, lines: list[dict], expected_letters: list[str], early_stop: bool) -> dict:
    observed = best.get("observed_initials", [])
    matched = int(best.get("matched_prefix", 0))
    expected_len = len(expected_letters)
    min_req = 1 if expected_len <= 2 else (2 if expected_len == 3 else min(MIN_MATCH_REQUIRED, expected_len))
    lcs = lcs_len(expected_letters, observed)
    cov_obs = lcs / max(1, len(observed))
    cov_exp = lcs / max(1, expected_len)
    weak_cut = False
    weak_reason = None
    force_cut = bool(best.get("best_mode") in FORCE_CUT_ON_MODES)

    if matched < min_req:
        begin_ok = (expected_len == 0) or (expected_letters[0] in observed[:3])
        weak_min_lcs = 1 if expected_len <= 2 else WEAK_MIN_LCS
        allow_weak = (
            ALLOW_WEAK_CUT
            and best.get("best_mode") in WEAK_ALLOWED_MODES
            and begin_ok
            and lcs >= weak_min_lcs
            and cov_exp >= WEAK_COV_EXP
            and cov_obs >= WEAK_COV_OBS
            and (len(observed) >= WEAK_MIN_OBS or expected_len <= 3)
        )
        if allow_weak:
            weak_cut = True
            weak_reason = f"weak_cut_low_match_{matched}_{expected_len}_lcs_{lcs}_covExp_{cov_exp:.2f}_covObs_{cov_obs:.2f}"
        elif force_cut:
            weak_cut = True
            weak_reason = f"force_cut_mode_{best.get('best_mode')}_low_match_{matched}_{expected_len}"
        else:
            return build_no_match_payload(
                reason=f"low_match_{matched}_{expected_len}",
                lines=lines,
                expected_letters=expected_letters,
                best={**best, "lcs": lcs, "cov_obs": cov_obs, "cov_exp": cov_exp},
                early_stop=early_stop,
            )

    prefix_hits = prefix_match_count(observed, expected_letters)
    bbox = bbox_ints(best)
    return {
        "matched": True,
        "matched_text": best["text"],
        "bbox": bbox,
        "y_cut": bbox[1],
        "match_score": int(best["match_score"]),
        "matched_prefix": matched,
        "expected_len": expected_len,
        "match_ratio": matched / expected_len if expected_len else 0.0,
        "prefix_hits": int(prefix_hits),
        "lcs": int(lcs),
        "cov_obs": float(cov_obs),
        "cov_exp": float(cov_exp),
        "best_mode": best.get("best_mode"),
        "weak_cut": bool(weak_cut),
        "weak_reason": weak_reason,
        "force_cut": bool(force_cut),
        "early_stop": bool(early_stop),
        "score_breakdown": {
            "score_formula": "m * 10 + heading_bonus + dot_bonus",
            "has_heading": bool(best.get("has_heading")),
            "has_dot": bool(best.get("has_dot")),
            "heading_bonus": 2 if best.get("has_heading") else 0,
            "dot_bonus": 1 if best.get("has_dot") else 0,
        },
        "ocr_candidates": public_candidates(lines, best=best),
    }


def build_no_match_payload(
    *,
    reason: str,
    lines: list[dict],
    expected_letters: list[str],
    best: dict | None,
    early_stop: bool,
) -> dict:
    matched = int(best.get("matched_prefix", 0)) if best else 0
    observed = best.get("observed_initials", []) if best else []
    expected_len = len(expected_letters)
    lcs = int(best.get("lcs", lcs_len(expected_letters, observed))) if best else 0
    cov_obs = float(best.get("cov_obs", lcs / max(1, len(observed)))) if best else 0.0
    cov_exp = float(best.get("cov_exp", lcs / max(1, expected_len))) if best else 0.0
    return {
        "matched": False,
        "reason": reason,
        "best_match_score": int(best.get("match_score", 0)) if best else 0,
        "matched_prefix": matched,
        "expected_len": expected_len,
        "match_ratio": matched / expected_len if expected_len else 0.0,
        "prefix_hits": prefix_match_count(observed, expected_letters),
        "lcs": lcs,
        "cov_obs": cov_obs,
        "cov_exp": cov_exp,
        "best_mode": best.get("best_mode") if best else None,
        "weak_cut": False,
        "force_cut": bool(best and best.get("best_mode") in FORCE_CUT_ON_MODES),
        "early_stop": bool(early_stop),
        "ocr_candidates": public_candidates(lines, best=best),
    }


def public_candidates(lines: list[dict], best: dict | None = None, limit: int = 20) -> list[dict]:
    out = []
    for line in lines[:limit]:
        item = {
            "text": line["text"],
            "bbox": bbox_ints(line),
            "score": float(line.get("score") or 0.0),
        }
        if best is not None and line["text"] == best.get("text"):
            item.update(
                {
                    "score": int(best.get("match_score", 0)),
                    "matched_prefix": int(best.get("matched_prefix", 0)),
                    "best_mode": best.get("best_mode"),
                }
            )
        out.append(item)
    return out


def draw_bbox(page_path: Path, output_path: Path, match_payload: dict | None, lines: list[dict]) -> None:
    import cv2

    image = cv2.imread(str(page_path))
    if image is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    for line in lines:
        x0, y0, x1, y1 = bbox_ints(line)
        cv2.rectangle(image, (max(0, x0), max(0, y0)), (min(width - 1, x1), min(height - 1, y1)), (0, 180, 255), 1)
    if match_payload and match_payload.get("bbox"):
        x0, y0, x1, y1 = match_payload["bbox"]
        cv2.line(image, (0, max(0, y0)), (width - 1, max(0, y0)), (0, 0, 255), 3)
        cv2.rectangle(image, (max(0, x0), max(0, y0)), (min(width - 1, x1), min(height - 1, y1)), (0, 255, 0), 2)
    cv2.imwrite(str(output_path), image)


def build_ocr() -> Any:
    import numpy as np

    if not hasattr(np, "sctypes"):
        np.sctypes = {
            "int": [np.int8, np.int16, np.int32, np.int64],
            "uint": [np.uint8, np.uint16, np.uint32, np.uint64],
            "float": [np.float16, np.float32, np.float64],
            "complex": [np.complex64, np.complex128],
            "others": [np.bool_, np.bytes_, np.str_, np.void],
        }

    module = __import__("paddleocr", fromlist=["Paddle" + "OCR"])
    ocr_class = getattr(module, "Paddle" + "OCR")
    try:
        return ocr_class(
            lang="vi",
            use_textline_orientation=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            text_det_limit_type="max",
            text_det_limit_side_len=4096,
        )
    except Exception:
        return ocr_class(lang="vi", det_limit_type="max", det_limit_side_len=4096)


def process_cutline_item(ocr: Any, item: dict, page_path: Path, bbox_path: Path) -> dict:
    import cv2

    image = cv2.imread(str(page_path))
    if image is None:
        raise RuntimeError(f"Could not read page image: {page_path}")

    result = ocr.ocr(image, cls=False)
    dets = parse_ocr_result(result)
    lines = group_to_lines(dets)
    match_payload = match_heading_title(
        lines,
        dets,
        heading=str(item.get("heading") or ""),
        title=str(item.get("title") or ""),
    )
    draw_bbox(page_path, bbox_path, match_payload if match_payload.get("matched") else None, lines)
    height, width = image.shape[:2]
    return {
        "chunk_name": item.get("chunk_name"),
        "page_number": item.get("page_number"),
        "image_file": item.get("image_file"),
        **match_payload,
        "image_width": int(width),
        "image_height": int(height),
    }


def main() -> None:
    sh("python -m pip -q install --upgrade pip")
    sh("python -m pip -q install paddlepaddle==3.3.0")
    sh("python -m pip -q uninstall -y paddleocr paddlex || true")
    sh("python -m pip -q install --no-deps paddleocr==2.7.3")
    sh("python -m pip -q install opencv-python-headless pyclipper shapely imgaug pillow tqdm lmdb attrdict fire rapidfuzz visualdl")

    run_request = load_request()
    request_id = str(run_request.get("request_id") or "unknown")
    write_status(request_id, "started")

    ocr = build_ocr()
    items = run_request.get("items")
    if isinstance(items, list) and items:
        results = []
        bbox_dir = WORKING_DIR / "bbox"
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            chunk_name = str(item.get("chunk_name") or f"item_{index:02d}")
            image_file = str(item.get("image_file") or f"pages/{chunk_name}.png")
            results.append(
                process_cutline_item(
                    ocr,
                    item,
                    find_input_path(image_file),
                    bbox_dir / f"{chunk_name}.png",
                )
            )

        payload = {
            "request_id": request_id,
            "job_id": run_request.get("job_id"),
            "lesson_name": run_request.get("lesson_name"),
            "mode": run_request.get("mode") or "lesson_cutline_full",
            "results": results,
        }
        write_json(WORKING_DIR / "cutline_results.json", payload)
        write_status(
            request_id,
            "completed",
            mode=payload["mode"],
            result_count=len(results),
            matched_count=sum(1 for item in results if item.get("matched")),
        )
        return

    page_path = find_input_file("page.png")
    match_payload = process_cutline_item(
        ocr,
        run_request,
        page_path,
        WORKING_DIR / "bbox.png",
    )

    payload = {
        "request_id": request_id,
        "job_id": run_request.get("job_id"),
        "lesson_name": run_request.get("lesson_name"),
        "chunk_name": run_request.get("chunk_name"),
        "page_number": run_request.get("page_number"),
        **{
            key: value
            for key, value in match_payload.items()
            if key not in {"chunk_name", "page_number"}
        },
    }
    write_json(WORKING_DIR / "cutline_result.json", payload)
    write_status(request_id, "completed", matched=bool(match_payload.get("matched")))


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
