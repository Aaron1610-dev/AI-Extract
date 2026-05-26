# KAGGLE_CUTLINE_READINESS.md

## 1. Mục tiêu

Tài liệu này mô tả cách kiểm tra readiness cho Kaggle/PaddleOCR cutline:

```text
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/chunk/{chunk_name}/cutline
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/finalize
```

Các endpoint này dùng Kaggle để chạy PaddleOCR. Backend AI-Extract không yêu cầu và không chạy `paddleocr`/`paddlepaddle` local.

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

One-chunk troubleshooting request chỉ upload package tối thiểu cho một chunk:

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

Finalize upload một package batch tối thiểu cho required cutlines của một selected lesson:

```text
pages/{chunk_name}.png
run_request.json
dataset-metadata.json
```

Batch `run_request.json` có `mode="lesson_cutline_full"` và `items[]`, mỗi item giữ `chunk_name`, `page_number`, `image_file`, `heading`, và `title`.

## 5. Kernel và output mong đợi

Kernel source tối thiểu nằm tại:

```text
app/pipeline/kaggle_kernels/debug-cutline-one-chunk/script.py
```

Kernel đọc `run_request.json`, chạy PaddleOCR trong môi trường Kaggle, rồi ghi one-chunk output:

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

Với finalize batch, kernel ghi:

```text
cutline_results.json
bbox/{chunk_name}.png
current_run_status.json
current_run_status_{request_id}.json
```

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

Normal one-call workflow là:

```text
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/chunk/{chunk_name}/cutline
-> detect y_cut bằng Kaggle/PaddleOCR
-> nếu matched và applicable thì auto-promote official doc/chunk_*.pdf
```

Endpoint không sửa:

- `chunk/{lesson_name}/{chunk_name}.json`
- `job.json`

Nếu promote chạy, endpoint update trực tiếp official PDF trong:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/
```

Endpoint đọc `debug/{chunk_name}/cutline.json`, ghi `debug/{chunk_name}/cutline_promote.json`, recut từ `lesson/doc/{lesson_name}.pdf`, rồi thay thế trực tiếp official PDFs trong:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/
```

Không có endpoint promote riêng, không tạo thêm folder PDF output nào, và không tạo preview/backup PDF folder. Rerun `/cutline` sẽ overwrite `doc/chunk_*.pdf` liên quan khi detection matched và applicable. Endpoint không sửa chunk JSON và không update job status.

`chunk_01` được hỗ trợ bằng cách crop từ `y_cut` tới bottom cho selected chunk. Với `chunk_02+`, endpoint chỉ promote khi `content_head=true`; previous chunk nhận phần top của page start, selected chunk nhận phần bottom. Với `content_head=false`, `/cutline` trả `promote_status=skipped`.

Full lesson workflow cho một selected lesson:

```text
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/finalize
```

Endpoint này không xử lý tất cả lessons và không phải global batch. Nó detect toàn bộ cutline cần thiết trong một selected lesson bằng một Kaggle batch run, build boundary map, rồi rebuild tất cả official PDFs của lesson trong một pass từ:

```text
workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf
```

Output trực tiếp:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_*.pdf
```

Summary:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/lesson_cutline_full.json
```

Nếu một required cutline fail hoặc confidence không đủ, endpoint ghi summary `status=failed` và không rebuild official PDFs.

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
