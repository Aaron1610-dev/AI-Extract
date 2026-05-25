# KAGGLE_CUTLINE_READINESS.md

## 1. Mục tiêu

Tài liệu này mô tả cách kiểm tra readiness cho endpoint debug cutline một chunk:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline
```

Endpoint này dùng Kaggle để chạy PaddleOCR. Backend AI-Extract không yêu cầu và không chạy `paddleocr`/`paddlepaddle` local.

## 2. Biến môi trường bắt buộc

```text
AI_EXTRACT_KAGGLE_USERNAME
AI_EXTRACT_KAGGLE_KEY
AI_EXTRACT_KAGGLE_DATASET_SLUG
AI_EXTRACT_KAGGLE_KERNEL_REF
```

Ý nghĩa:

- `AI_EXTRACT_KAGGLE_USERNAME`: Kaggle username dùng để tạo/version dataset và push kernel.
- `AI_EXTRACT_KAGGLE_KEY`: Kaggle API key. Không log, không commit.
- `AI_EXTRACT_KAGGLE_DATASET_SLUG`: slug dataset debug, ví dụ `ai-extract-cutline-debug`. Nếu chỉ là slug, service tự ghép thành `{username}/{slug}`.
- `AI_EXTRACT_KAGGLE_KERNEL_REF`: kernel ref đầy đủ, ví dụ `{username}/debug-cutline-one-chunk`.

Biến optional:

```text
AI_EXTRACT_KAGGLE_WORK_DIR
AI_EXTRACT_KAGGLE_POLL_SECONDS
AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS
```

## 3. Kiểm tra readiness

Chạy:

```bash
python3 scripts/check_kaggle_cutline_ready.py
```

Ví dụ output khi sẵn sàng:

```json
{
  "ready": true,
  "missing_env": [],
  "kernel_script_exists": true,
  "backend_uses_local_paddleocr": false,
  "uses_external_command_placeholder": false,
  "requirements_ok": true,
  "requirements_missing": [],
  "notes": []
}
```

Ví dụ output khi thiếu config:

```json
{
  "ready": false,
  "missing_env": ["AI_EXTRACT_KAGGLE_USERNAME"],
  "kernel_script_exists": true,
  "backend_uses_local_paddleocr": false,
  "uses_external_command_placeholder": false,
  "requirements_ok": true,
  "requirements_missing": [],
  "notes": ["Missing AI_EXTRACT_KAGGLE_USERNAME"]
}
```

Script này không gọi Kaggle, không push dataset, không push kernel và không xử lý chunk.

## 4. Package gửi lên Kaggle

Mỗi request chỉ upload package tối thiểu cho một chunk:

```text
page.png
run_request.json
dataset-metadata.json
```

`run_request.json` có shape:

```json
{
  "request_id": "...",
  "job_id": "...",
  "lesson_name": "lesson_01",
  "chunk_name": "chunk_03",
  "page_number": 10,
  "heading": "3.",
  "title": "..."
}
```

Không upload:

- `original.pdf`
- full lesson PDF
- toàn bộ `workspace`
- các chunk/lesson/topic khác

## 5. Kernel và output mong đợi

Kernel source tối thiểu nằm tại:

```text
app/pipeline/kaggle_kernels/debug-cutline-one-chunk/script.py
```

Kernel đọc `run_request.json` và `page.png`, chạy PaddleOCR trong môi trường Kaggle, rồi ghi:

```text
cutline_result.json
bbox.png
current_run_status.json
current_run_status_{request_id}.json
```

`cutline_result.json` phải chứa đúng `request_id`:

```json
{
  "request_id": "...",
  "matched": true,
  "matched_text": "...",
  "bbox": [120, 345, 980, 390],
  "y_cut": 345,
  "ocr_candidates": []
}
```

Backend validate `request_id`; nếu output thuộc request cũ/stale, request hiện tại sẽ fail.

Kernel một-chunk hiện tái dùng logic scoring/matching đã debug từ thesis cũ trong `FastAPI-Khoa-Luan/gemini_pipeline/sgk_extract/chunk_postprocess.py`, gồm:

- `_score(m, has_heading, has_dot) = m * 10 + heading_bonus + dot_bonus`
- `prefix_match_count(...)`
- `robust_match_count(...)`
- `try_merge_title_from_next_lines(...)`
- các mode `prefix_line`, `heading_left_title`, `same_line`, `merge_next`
- `weak_cut`, `force_cut`, `FORCE_CUT_ON_MODES`, `ALLOW_WEAK_CUT`
- `early_stop=true` khi matched đủ toàn bộ expected title letters

`cutline_result.json` còn có các debug fields:

```json
{
  "match_score": 83,
  "matched_prefix": 8,
  "expected_len": 10,
  "match_ratio": 0.8,
  "prefix_hits": 8,
  "lcs": 8,
  "cov_obs": 0.8,
  "cov_exp": 0.8,
  "best_mode": "prefix_line",
  "weak_cut": false,
  "force_cut": true,
  "early_stop": true
}
```

## 6. Output trong workspace

Sau khi Kaggle chạy xong và output hợp lệ, backend ghi/copy:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/cutline.json
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/page.png
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/bbox.png
```

Thư mục debug ổn định theo từng chunk. Chạy lại cùng chunk sẽ overwrite các file trong `debug/{chunk_name}/`. `request_id` chỉ được lưu bên trong `cutline.json` để kiểm tra output stale, không được đưa vào tên thư mục.

Endpoint không sửa:

- `chunk/{lesson_name}/{chunk_name}.json`
- `chunk/{lesson_name}/doc/{chunk_name}.pdf`
- `job.json`

Stage B apply cutline là endpoint riêng và không gọi Kaggle:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline/apply
```

Endpoint này đọc `debug/{chunk_name}/cutline.json` đã có, ghi `debug/{chunk_name}/cutline_apply.json`, và tạo PDF recut an toàn trong:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc_cutline/
```

Các PDF chính trong `doc/` không bị overwrite.

Stage C promote cutline là endpoint riêng và cũng không gọi Kaggle:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline/promote
```

Endpoint này đọc `debug/{chunk_name}/cutline.json`, ghi `debug/{chunk_name}/cutline_promote.json`, recut từ `lesson/doc/{lesson_name}.pdf`, rồi thay thế official PDFs trong:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/
```

Trước khi replace, endpoint backup bản official đầu tiên vào:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc_backup_before_cutline/
```

`chunk_01` được hỗ trợ bằng cách crop từ `y_cut` tới bottom cho selected chunk. Với `chunk_02+`, endpoint chỉ promote khi `content_head=true`; previous chunk nhận phần top của page start, selected chunk nhận phần bottom.

## 7. Lỗi thường gặp

- Thiếu biến môi trường: chạy readiness script để xem `missing_env`.
- Thiếu Kaggle CLI: cài package `kaggle` trong môi trường backend.
- Dataset/kernel ref sai: kiểm tra `AI_EXTRACT_KAGGLE_DATASET_SLUG` và `AI_EXTRACT_KAGGLE_KERNEL_REF`.
- Kernel timeout: tăng `AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS`.
- Output stale: backend sẽ fail nếu `request_id` trong output không khớp.

## 8. Ghi chú bảo mật

- Không in giá trị `AI_EXTRACT_KAGGLE_KEY`.
- Không commit `app/core/config.env`.
- Chỉ log tên biến thiếu, không log secret value.
- Chỉ upload `page.png` và `run_request.json` cho đúng chunk được chọn.
