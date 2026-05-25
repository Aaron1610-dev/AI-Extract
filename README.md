# AI-Extract

AI-Extract là dịch vụ FastAPI để trích xuất cấu trúc sách giáo khoa từ PDF. Pipeline hiện tại đi theo hướng **file-based** và **review/debug-first**: backend tạo các file JSON/PDF trong `workspace/`, developer hoặc reviewer kiểm tra output, sau đó mới chạy các bước tiếp theo.

Project hiện hỗ trợ:

- Upload PDF sách giáo khoa và tạo `job_id`.
- Trích xuất Topic/Lesson bằng Gemini.
- Detect offset giữa số trang in và số trang PDF thật bằng OCR vùng số trang cuối trang.
- Review và approve Topic/Lesson trước khi build lesson PDF.
- Tách chunk cho một lesson bằng Gemini.
- Detect cutline bằng Kaggle/PaddleOCR để sửa ranh giới chunk bắt đầu giữa trang.
- Rebuild official chunk PDFs trực tiếp trong `chunk/{lesson_name}/doc/`.
- Extract keyword từ lesson/chunk PDF đã finalized.

Project hiện **chưa** import/sync dữ liệu vào MongoDB, MinIO, PostgreSQL hoặc Neo4j.

## 1. Tổng Quan

Output chính nằm dưới:

```text
workspace/
  uploads/{job_id}/original.pdf
  outputs/{job_id}/
```

Ví dụ xuyên suốt README:

```text
job_id      = 3ce9f3cf-3a3a-4c49-b908-fabb50567db1
lesson_name = lesson_01
chunk_name  = chunk_03
base_url    = http://127.0.0.1:8101
```

Pipeline thường dùng:

```text
Upload PDF
-> Extract topics
-> Review/approve topics
-> Build lessons
-> Review/approve lessons
-> Extract chunks cho một lesson
-> Full lesson cutline cho một lesson
-> Auto keyword extraction sau cutline thành công
```

Có thể chạy keyword extraction riêng nếu chỉ muốn regenerate file keyword.

## 2. Cài Đặt Và Chạy Server

Tạo virtual environment và cài dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tạo file cấu hình local:

```text
app/core/config.env
```

Không commit file này. Chỉ dùng placeholder trong tài liệu:

```env
APP_NAME=AI-Extract
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8101

GEMINI_API_KEYS=YOUR_GEMINI_KEY_1,YOUR_GEMINI_KEY_2
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MIN_INTERVAL=4.5
GEMINI_COOLDOWN_SECONDS=300

AI_EXTRACT_KAGGLE_USERNAME=YOUR_KAGGLE_USERNAME
AI_EXTRACT_KAGGLE_KEY=YOUR_KAGGLE_API_KEY
AI_EXTRACT_KAGGLE_DATASET_SLUG=ai-extract-cutline-debug
AI_EXTRACT_KAGGLE_KERNEL_REF=YOUR_KAGGLE_USERNAME/debug-cutline-one-chunk
```

Chạy server:

```bash
python3 run.py
```

`run.py` bật Uvicorn reload nhưng chỉ watch source trong `app/` và exclude `workspace/`. Điều này tránh server restart khi pipeline tạo file generated như:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/kaggle/kernel/script.py
```

Khi chạy request dài như Kaggle/cutline, không nên dùng `uvicorn --reload` kiểu watch toàn repo hoặc watch `workspace/`.

## 3. Cấu Hình Gemini Và Kaggle

Gemini được dùng cho:

- Topic/Lesson extraction.
- Chunk debug extraction.
- Keyword extraction.

Kaggle/PaddleOCR được dùng cho cutline. Backend không yêu cầu cài `paddleocr` hoặc `paddlepaddle` local.

Biến Kaggle bắt buộc:

```text
AI_EXTRACT_KAGGLE_USERNAME
AI_EXTRACT_KAGGLE_KEY
AI_EXTRACT_KAGGLE_DATASET_SLUG
AI_EXTRACT_KAGGLE_KERNEL_REF
```

Biến Kaggle optional:

```text
AI_EXTRACT_KAGGLE_WORK_DIR
AI_EXTRACT_KAGGLE_POLL_SECONDS
AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS
```

Kiểm tra readiness không gọi Kaggle:

```bash
python3 scripts/check_kaggle_cutline_ready.py
```

Không commit Gemini API key, Kaggle API key, `kaggle.json` hoặc `app/core/config.env`.

## 4. API Tổng Quan

Các route public hiện được include trong `app/main.py`:

```text
GET  /health
GET  /api/debug/gemini-keys

POST /api/extract/jobs
GET  /api/extract/jobs/{job_id}

POST /api/extract/jobs/{job_id}/topics/extract
GET  /api/extract/jobs/{job_id}/topics
PUT  /api/extract/jobs/{job_id}/topics
POST /api/extract/jobs/{job_id}/topics/approve

POST /api/extract/jobs/{job_id}/lessons/build
GET  /api/extract/jobs/{job_id}/lessons
PUT  /api/extract/jobs/{job_id}/lessons
POST /api/extract/jobs/{job_id}/lessons/approve

POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/cutline/full

POST /api/extract/jobs/{job_id}/keywords/debug/lesson/{lesson_name}/extract

GET  /api/keywords/prompt-versions
POST /api/keywords/debug-prompt
POST /api/keywords/debug-filter
POST /api/keywords/extract
POST /api/keywords/extract-analysis
```

Không có public `/cutline/promote` endpoint trong workflow hiện tại.

## 5. Health Và Debug

### `GET /health`

Response:

```json
{
  "status": "ok",
  "service": "AI-Extract",
  "env": "development"
}
```

### `GET /api/debug/gemini-keys`

Trả trạng thái rotation/cooldown của Gemini keys. Endpoint này phục vụ debug vận hành, không trả secret value.

## 6. Job Upload

### `POST /api/extract/jobs`

Tạo một extraction job từ file PDF upload.

Request:

```bash
curl -X POST \
  -F "file=@/path/to/textbook.pdf" \
  http://127.0.0.1:8101/api/extract/jobs
```

Response schema:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "uploaded",
  "source_file": "textbook.pdf",
  "upload_path": "workspace/uploads/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/original.pdf",
  "output_dir": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "created_at": "2026-05-26T09:00:00Z",
  "updated_at": "2026-05-26T09:00:00Z"
}
```

Files được tạo:

```text
workspace/uploads/{job_id}/original.pdf
workspace/outputs/{job_id}/job.json
workspace/outputs/{job_id}/topic/
workspace/outputs/{job_id}/lesson/
```

`job.json` chứa metadata job theo response trên.

### `GET /api/extract/jobs/{job_id}`

Đọc lại `job.json`.

## 7. Topic Extraction

### `POST /api/extract/jobs/{job_id}/topics/extract`

Trích xuất Topic từ front matter/table of contents bằng Gemini. Endpoint có query params:

```text
offset=auto | none | {integer}
split_pdf=true | false
```

Ví dụ:

```bash
curl -X POST \
  "http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/topics/extract?offset=auto&split_pdf=true"
```

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "reviewing_topics",
  "offset": 8,
  "topics": [
    {
      "name": "topic_01",
      "start": 1,
      "end": 36,
      "heading": "CHƯƠNG I",
      "title": "Mệnh đề và tập hợp"
    }
  ]
}
```

Files thường được tạo:

```text
workspace/outputs/{job_id}/topic/front_matter.pdf
workspace/outputs/{job_id}/topic/topic_raw.json
workspace/outputs/{job_id}/topic/topics.json
workspace/outputs/{job_id}/topic/doc/topic_01.pdf
workspace/outputs/{job_id}/lesson/lesson_raw.json
```

Ý nghĩa file:

- `front_matter.pdf`: PDF nhỏ từ phần đầu sách/mục lục để Gemini đọc cấu trúc.
- `topic_raw.json`: raw Gemini/OCR output để debug. Shape có thể thay đổi theo pipeline nội bộ, không nên xem là stable public schema.
- `topics.json`: danh sách topic reviewable theo schema `TopicItem`.
- `topic/doc/topic_*.pdf`: PDF đã split theo range topic nếu `split_pdf=true`.
- `lesson/lesson_raw.json`: danh sách lesson thô từ Gemini, được giữ để bước `/lessons/build` lọc/map vào approved topics.

`topics.json`:

```json
[
  {
    "name": "topic_01",
    "start": 1,
    "end": 36,
    "heading": "CHƯƠNG I",
    "title": "Mệnh đề và tập hợp"
  }
]
```

Valid topic heading thường gồm:

```text
CHỦ ĐỀ 1
CHỦ ĐỀ I
CHƯƠNG 1
CHƯƠNG I
1.
I.
```

Heading quá chung chung như `HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM` nên bị loại nếu không giống topic/chapter thật.

### `GET /api/extract/jobs/{job_id}/topics`

Đọc `topic/topics.json`.

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "reviewing_topics",
  "topics": [
    {
      "name": "topic_01",
      "start": 1,
      "end": 36,
      "heading": "CHƯƠNG I",
      "title": "Mệnh đề và tập hợp"
    }
  ],
  "topics_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/topic/topics.json"
}
```

### `PUT /api/extract/jobs/{job_id}/topics`

Cập nhật danh sách topics sau review.

Request body:

```json
{
  "topics": [
    {
      "name": "topic_01",
      "start": 1,
      "end": 36,
      "heading": "CHƯƠNG I",
      "title": "Mệnh đề và tập hợp"
    }
  ]
}
```

Response giống `GET /topics` và ghi lại `topic/topics.json`.

### `POST /api/extract/jobs/{job_id}/topics/approve`

Approve topics để bước lesson có thể chạy.

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "topics_approved",
  "topics": [
    {
      "name": "topic_01",
      "start": 1,
      "end": 36,
      "heading": "CHƯƠNG I",
      "title": "Mệnh đề và tập hợp"
    }
  ],
  "topics_approved_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/topic/topics_approved.json"
}
```

File được tạo:

```text
workspace/outputs/{job_id}/topic/topics_approved.json
```

## 8. Lesson Build Và Review

### `POST /api/extract/jobs/{job_id}/lessons/build`

Build lessons từ `topic/topics_approved.json` và `lesson/lesson_raw.json`. Lessons được map vào valid topics. Lesson có `heading` null/missing hoặc không reviewable sẽ bị filter.

Request:

```bash
curl -X POST \
  http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/lessons/build
```

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "reviewing_lessons",
  "lessons": [
    {
      "name": "lesson_01",
      "start": 1,
      "end": 12,
      "heading": "Bài 1",
      "title": "Mệnh đề",
      "topic_name": "topic_01",
      "topic_title": "Mệnh đề và tập hợp"
    }
  ],
  "lessons_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/lesson/lessons.json"
}
```

Files được đọc/ghi:

```text
workspace/outputs/{job_id}/lesson/lesson_raw.json
workspace/outputs/{job_id}/lesson/lessons.json
workspace/outputs/{job_id}/lesson/doc/lesson_01.pdf
```

Ý nghĩa file:

- `lesson_raw.json`: raw lesson extraction/debug output đã được tạo từ Topic extraction.
- `lessons.json`: danh sách lesson reviewable theo schema `LessonItem`.
- `lesson/doc/{lesson_name}.pdf`: PDF chính của từng lesson.

`lessons.json`:

```json
[
  {
    "name": "lesson_01",
    "start": 1,
    "end": 12,
    "heading": "Bài 1",
    "title": "Mệnh đề",
    "topic_name": "topic_01",
    "topic_title": "Mệnh đề và tập hợp"
  }
]
```

### `GET /api/extract/jobs/{job_id}/lessons`

Đọc `lesson/lessons.json`.

### `PUT /api/extract/jobs/{job_id}/lessons`

Cập nhật lessons sau review.

Request body:

```json
{
  "lessons": [
    {
      "name": "lesson_01",
      "start": 1,
      "end": 12,
      "heading": "Bài 1",
      "title": "Mệnh đề",
      "topic_name": "topic_01",
      "topic_title": "Mệnh đề và tập hợp"
    }
  ]
}
```

### `POST /api/extract/jobs/{job_id}/lessons/approve`

Approve lessons.

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "status": "lessons_approved",
  "lessons": [
    {
      "name": "lesson_01",
      "start": 1,
      "end": 12,
      "heading": "Bài 1",
      "title": "Mệnh đề",
      "topic_name": "topic_01",
      "topic_title": "Mệnh đề và tập hợp"
    }
  ],
  "lessons_approved_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/lesson/lessons_approved.json"
}
```

File được tạo:

```text
workspace/outputs/{job_id}/lesson/lessons_approved.json
```

## 9. Chunk Debug Extraction

### `POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}`

Endpoint này chỉ xử lý một lesson được chọn. Nó dùng Gemini để detect heading cấp cao bên trong lesson PDF, ví dụ `1.`, `2.`, `3.`.

Request:

```bash
curl -X POST \
  http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunks/debug/lesson/lesson_01
```

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "chunks": [
    {
      "name": "chunk_01",
      "start": 1,
      "end": 3,
      "first_chunk": true,
      "heading": "1.",
      "title": "Mệnh đề"
    },
    {
      "name": "chunk_02",
      "start": 4,
      "end": 6,
      "content_head": true,
      "heading": "2.",
      "title": "Tập hợp"
    }
  ]
}
```

Files được tạo:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/chunk_01.json
workspace/outputs/{job_id}/chunk/{lesson_name}/chunk_02.json
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_01.pdf
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_02.pdf
```

`chunk_01.json`:

```json
{
  "name": "chunk_01",
  "start": 1,
  "end": 3,
  "first_chunk": true,
  "heading": "1.",
  "title": "Mệnh đề"
}
```

`chunk_02.json`:

```json
{
  "name": "chunk_02",
  "start": 4,
  "end": 6,
  "content_head": true,
  "heading": "2.",
  "title": "Tập hợp"
}
```

Chunk PDFs ban đầu được cắt theo page range. Nếu heading chunk bắt đầu giữa trang, cutline stage sẽ sửa lại official PDFs.

## 10. One-Chunk Cutline

### `POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline`

Đây là workflow một API call cho một chunk:

1. Validate job, lesson PDF, selected chunk JSON.
2. Render trang `chunk.start` thành `page.png`.
3. Upload package tối thiểu lên Kaggle.
4. Kaggle chạy PaddleOCR.
5. Kernel dùng logic matching/cutline đã port từ thesis cũ.
6. Backend ghi debug artifacts.
7. Nếu matched và applicable, backend tự update official PDFs trong `chunk/{lesson_name}/doc/`.

Request:

```bash
curl -X POST \
  http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunks/debug/lesson/lesson_01/chunk/chunk_03/cutline
```

Response khi matched và promoted:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "chunk_name": "chunk_03",
  "matched": true,
  "page_number": 10,
  "heading": "3.",
  "title": "Các phép toán trên tập hợp",
  "matched_text": "3. Các phép toán trên tập hợp",
  "bbox": [120, 345, 980, 390],
  "y_cut": 345,
  "match_score": 83,
  "matched_prefix": 8,
  "expected_len": 10,
  "match_ratio": 0.8,
  "best_mode": "prefix_line",
  "weak_cut": false,
  "force_cut": true,
  "early_stop": true,
  "debug_json_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_03/cutline.json",
  "debug_page_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_03/page.png",
  "debug_bbox_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_03/bbox.png",
  "promoted": true,
  "promote_status": "promoted",
  "previous_chunk": "chunk_02",
  "selected_chunk_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/doc/chunk_03.pdf",
  "previous_chunk_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/doc/chunk_02.pdf",
  "debug_promote_json_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_03/cutline_promote.json"
}
```

Response khi matched nhưng không cần promote vì `content_head=false`:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "chunk_name": "chunk_04",
  "matched": true,
  "page_number": 11,
  "heading": "4.",
  "title": "Luyện tập",
  "y_cut": 240,
  "debug_json_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_04/cutline.json",
  "promoted": false,
  "promote_status": "skipped",
  "promote_reason": "Selected chunk does not have content_head=true; page-range doc is already sufficient."
}
```

Response khi detection fail:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "chunk_name": "chunk_03",
  "matched": false,
  "page_number": 10,
  "heading": "3.",
  "title": "Các phép toán trên tập hợp",
  "reason": "No OCR candidate reached minimum threshold",
  "debug_json_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/chunk_03/cutline.json",
  "promoted": false,
  "promote_status": "not_run"
}
```

Files debug:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/page.png
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/bbox.png
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/cutline.json
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}/cutline_promote.json
```

`cutline.json` thường chứa:

```json
{
  "request_id": "0b945df4-1f4d-4b7a-8ed3-4c5b0b1b0ef6",
  "matched": true,
  "matched_text": "3. Các phép toán trên tập hợp",
  "bbox": [120, 345, 980, 390],
  "y_cut": 345,
  "image_height": 1754,
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
  "early_stop": true,
  "ocr_candidates": []
}
```

`cutline_promote.json` thường chứa:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "selected_chunk": "chunk_03",
  "previous_chunk": "chunk_02",
  "source_lesson_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/lesson/doc/lesson_01.pdf",
  "page_number": 10,
  "y_cut_image": 345,
  "image_height": 1754,
  "pdf_page_height": 842.0,
  "y_cut_pdf": 165.6,
  "official_outputs": {
    "previous_chunk_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/doc/chunk_02.pdf",
    "selected_chunk_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/doc/chunk_03.pdf"
  },
  "promoted": true,
  "backup_created": false
}
```

Official PDFs được update trực tiếp:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_*.pdf
```

Không tạo:

```text
doc_cutline/
doc_backup_before_cutline/
```

Logic matching tái dùng từ thesis cũ gồm `_score`, `prefix_match_count`, `robust_match_count`, `try_merge_title_from_next_lines`, `weak_cut`, `force_cut`, `early_stop`, `matched_prefix`, `match_score`, `lcs`, `cov_obs`, `cov_exp`, `best_mode`.

## 11. Full-Lesson Cutline

### `POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/cutline/full`

Endpoint này xử lý cutline cho **một selected lesson**, không xử lý tất cả lessons và không phải global batch.

Workflow:

1. Load `chunk/{lesson_name}/chunk_*.json`.
2. Sort chunks theo thứ tự số.
3. Detect toàn bộ required cutlines trước:
   - `chunk_01` nếu `first_chunk=true`.
   - `chunk_02+` nếu `content_head=true`.
4. Skip chunk có `content_head=false`.
5. Nếu có required cutline fail, không rebuild official PDFs.
6. Nếu tất cả required cutlines pass, build boundary map.
7. Rebuild toàn bộ official `chunk_*.pdf` của lesson trong một pass từ `lesson/doc/{lesson_name}.pdf`.
8. Sau khi PDF rebuild thành công, tự chạy keyword extraction cho cùng lesson.

Request:

```bash
curl -X POST \
  http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunks/debug/lesson/lesson_01/cutline/full
```

Response khi completed:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "status": "completed",
  "processed_chunks": ["chunk_01", "chunk_03"],
  "skipped_chunks": [
    {
      "chunk_name": "chunk_02",
      "reason": "content_head=false"
    }
  ],
  "failed_chunks": [],
  "updated_pdfs": ["chunk_01.pdf", "chunk_02.pdf", "chunk_03.pdf"],
  "debug_summary_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/lesson_cutline_full.json",
  "keyword_extracted": true,
  "keyword_results": [
    {
      "chunk_name": "chunk_01",
      "keyword_count": 5,
      "keywords": [
        {
          "keyword_name": "Mệnh đề"
        },
        {
          "keyword_name": "Mệnh đề toán học"
        },
        {
          "keyword_name": "Mệnh đề phủ định"
        },
        {
          "keyword_name": "Kí hiệu ∀"
        },
        {
          "keyword_name": "Tính đúng sai"
        }
      ],
      "keyword_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/keyword/keyword_chunk_01.json"
    }
  ],
  "keyword_error": null
}
```

Response khi cutline fail:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "status": "failed",
  "processed_chunks": ["chunk_01"],
  "skipped_chunks": [],
  "failed_chunks": [
    {
      "chunk_name": "chunk_03",
      "reason": "No OCR candidate reached minimum threshold"
    }
  ],
  "updated_pdfs": [],
  "debug_summary_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/lesson_cutline_full.json",
  "keyword_extracted": false,
  "keyword_results": [],
  "keyword_error": null
}
```

Response khi PDF rebuild xong nhưng keyword fail:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "status": "completed_with_keyword_error",
  "processed_chunks": ["chunk_01", "chunk_03"],
  "skipped_chunks": [],
  "failed_chunks": [],
  "updated_pdfs": ["chunk_01.pdf", "chunk_02.pdf", "chunk_03.pdf"],
  "debug_summary_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/debug/lesson_cutline_full.json",
  "keyword_extracted": false,
  "keyword_results": [],
  "keyword_error": "Gemini keyword extraction failed: quota exceeded"
}
```

Summary file:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/lesson_cutline_full.json
```

`lesson_cutline_full.json` khi thành công:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "source_lesson_pdf": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/lesson/doc/lesson_01.pdf",
  "processed_chunks": ["chunk_01", "chunk_03"],
  "skipped_chunks": [
    {
      "chunk_name": "chunk_02",
      "reason": "content_head=false"
    }
  ],
  "failed_chunks": [],
  "updated_pdfs": ["chunk_01.pdf", "chunk_02.pdf", "chunk_03.pdf"],
  "cutline_boundaries": {
    "chunk_01": {
      "page_number": 2,
      "y_cut_image": 329,
      "y_cut_pdf": 158.2,
      "match_score": 83,
      "best_mode": "prefix_line"
    }
  },
  "status": "completed",
  "keyword_extracted": true,
  "keyword_paths": [
    "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/keyword/keyword_chunk_01.json"
  ]
}
```

Full lesson cutline luôn rebuild từ:

```text
workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf
```

và ghi đè official PDFs:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_*.pdf
```

Endpoint không update job status, không đổi chunk JSON schema và không tạo backup folder.

## 12. Keyword Extraction Theo Lesson

### `POST /api/extract/jobs/{job_id}/keywords/debug/lesson/{lesson_name}/extract`

Endpoint này chạy keyword extraction cho một lesson. Nó cũng được gọi tự động sau khi `/cutline/full` rebuild PDFs thành công.

Rules:

- Nếu lesson có đúng một chunk:
  - Source PDF: `workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf`
  - Bắt buộc đúng 10 keywords.
  - Output: `workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keyword_chunk_01.json`

- Nếu lesson có nhiều chunk:
  - Source PDFs: `workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_*.pdf`
  - Bắt buộc đúng 5 keywords cho mỗi chunk.
  - Output: `workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keyword_chunk_*.json`

Request:

```bash
curl -X POST \
  http://127.0.0.1:8101/api/extract/jobs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/keywords/debug/lesson/lesson_01/extract
```

Response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "chunk_count": 3,
  "results": [
    {
      "chunk_name": "chunk_01",
      "keyword_count": 5,
      "keywords": [
        {
          "keyword_name": "Mệnh đề"
        },
        {
          "keyword_name": "Mệnh đề toán học"
        },
        {
          "keyword_name": "Mệnh đề phủ định"
        },
        {
          "keyword_name": "Kí hiệu ∀"
        },
        {
          "keyword_name": "Tính đúng sai"
        }
      ],
      "keyword_path": "workspace/outputs/3ce9f3cf-3a3a-4c49-b908-fabb50567db1/chunk/lesson_01/keyword/keyword_chunk_01.json"
    }
  ]
}
```

Keyword output file:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keyword_chunk_01.json
```

File JSON:

```json
{
  "chunk_name": "chunk_01",
  "keyword_count": 5,
  "keywords": [
    {
      "keyword_name": "Mệnh đề"
    },
    {
      "keyword_name": "Mệnh đề toán học"
    },
    {
      "keyword_name": "Mệnh đề phủ định"
    },
    {
      "keyword_name": "Kí hiệu ∀"
    },
    {
      "keyword_name": "Tính đúng sai"
    }
  ]
}
```

Với one-chunk lesson, `keyword_count` là `10` và file vẫn là `keyword_chunk_01.json`.

Service normalize keyword bằng cách strip whitespace, bỏ empty keyword, bỏ duplicate case-insensitive và preserve order. Nếu Gemini trả thiếu, service retry tối đa 3 lần để lấy keyword bổ sung. Nếu vẫn không đủ đúng target count, endpoint fail và không ghi file keyword incomplete.

Không tạo:

```text
workspace/outputs/{job_id}/keyword/{lesson_name}/
keywords_summary.json
*_keywords_raw.json
```

Keyword JSON không chứa `reason`, `confidence`, `source_type`, `source_name`, `source_pdf`, `lesson_name` hoặc `lesson_title`.

## 13. Runtime Keyword APIs

Các endpoint này phục vụ keyword extraction từ query text, khác với lesson keyword extraction từ PDF:

```text
GET  /api/keywords/prompt-versions
POST /api/keywords/debug-prompt
POST /api/keywords/debug-filter
POST /api/keywords/extract
POST /api/keywords/extract-analysis
```

Request cho `/api/keywords/extract`:

```json
{
  "query": "bài toán mệnh đề toán học",
  "max_keywords": 10,
  "model": "gemini-2.5-flash",
  "prompt_version": "strict",
  "include_raw_response": false,
  "wait_for_available_key": false
}
```

Response:

```json
{
  "query": "bài toán mệnh đề toán học",
  "raw_keywords": ["mệnh đề", "mệnh đề toán học"],
  "filtered_keywords": ["mệnh đề", "mệnh đề toán học"],
  "model": "gemini-2.5-flash",
  "prompt_version": "strict",
  "raw_response": null
}
```

## 14. Workspace Output Tổng Hợp

Ví dụ output sau khi chạy các stage chính:

```text
workspace/
  uploads/
    3ce9f3cf-3a3a-4c49-b908-fabb50567db1/
      original.pdf

  outputs/
    3ce9f3cf-3a3a-4c49-b908-fabb50567db1/
      job.json

      topic/
        front_matter.pdf
        topic_raw.json
        topics.json
        topics_approved.json
        doc/
          topic_01.pdf

      lesson/
        lesson_raw.json
        lessons.json
        lessons_approved.json
        doc/
          lesson_01.pdf
          lesson_02.pdf

      chunk/
        lesson_01/
          chunk_01.json
          chunk_02.json
          chunk_03.json
          doc/
            chunk_01.pdf
            chunk_02.pdf
            chunk_03.pdf
          debug/
            chunk_01/
              page.png
              bbox.png
              cutline.json
              cutline_promote.json
              kaggle/
                dataset/
                  page.png
                  run_request.json
                  dataset-metadata.json
                kernel/
                  kernel-metadata.json
                  script.py
            lesson_cutline_full.json
          keyword/
            keyword_chunk_01.json
            keyword_chunk_02.json
            keyword_chunk_03.json
```

Các file chính:

| File | Nội dung |
| --- | --- |
| `job.json` | Metadata job và status hiện tại. |
| `topic/topic_raw.json` | Raw debug output từ topic extraction. |
| `topic/topics.json` | Topics reviewable. |
| `topic/topics_approved.json` | Topics đã approve. |
| `lesson/lesson_raw.json` | Raw debug output từ lesson build. |
| `lesson/lessons.json` | Lessons reviewable. |
| `lesson/lessons_approved.json` | Lessons đã approve. |
| `lesson/doc/{lesson_name}.pdf` | PDF của lesson. |
| `chunk/{lesson_name}/chunk_*.json` | Metadata chunk. |
| `chunk/{lesson_name}/doc/chunk_*.pdf` | Official finalized chunk PDFs. |
| `chunk/{lesson_name}/debug/{chunk_name}/cutline.json` | Kết quả cutline detection. |
| `chunk/{lesson_name}/debug/{chunk_name}/cutline_promote.json` | Metadata lần update official PDF từ cutline. |
| `chunk/{lesson_name}/debug/lesson_cutline_full.json` | Summary full-lesson cutline. |
| `chunk/{lesson_name}/keyword/keyword_chunk_*.json` | Keyword output tối giản cho từng chunk. |

## 15. Thứ Tự Chạy Gợi Ý

1. Upload PDF:

```text
POST /api/extract/jobs
```

2. Extract topics:

```text
POST /api/extract/jobs/{job_id}/topics/extract?offset=auto&split_pdf=true
```

3. Review topics:

```text
GET /api/extract/jobs/{job_id}/topics
PUT /api/extract/jobs/{job_id}/topics
```

4. Approve topics:

```text
POST /api/extract/jobs/{job_id}/topics/approve
```

5. Build lessons:

```text
POST /api/extract/jobs/{job_id}/lessons/build
```

6. Review lessons:

```text
GET /api/extract/jobs/{job_id}/lessons
PUT /api/extract/jobs/{job_id}/lessons
```

7. Approve lessons:

```text
POST /api/extract/jobs/{job_id}/lessons/approve
```

8. Extract chunks cho một lesson:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}
```

9. Rebuild cutline cho cả selected lesson và auto extract keywords:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/cutline/full
```

10. Nếu cần chạy lại keyword extraction:

```text
POST /api/extract/jobs/{job_id}/keywords/debug/lesson/{lesson_name}/extract
```

## 16. Lỗi Thường Gặp

| Trường hợp | HTTP status thường gặp | Cách xử lý |
| --- | --- | --- |
| Job không tồn tại | `404` | Kiểm tra `job_id` và `workspace/outputs/{job_id}/job.json`. |
| Chưa approve topics mà build lessons | `409` | Chạy `/topics/approve` trước. |
| Lesson PDF thiếu | `404` | Kiểm tra `workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf`. |
| Chunk JSON thiếu | `404` hoặc `400` | Chạy chunk debug extraction cho lesson trước. |
| Kaggle config thiếu | `503` | Chạy `python3 scripts/check_kaggle_cutline_ready.py`. |
| Cutline detection fail | Response `status=failed` hoặc `matched=false` | Xem `cutline.json`, `bbox.png`, OCR candidates. |
| Keyword thiếu số lượng sau retry | `500` | Xem lỗi Gemini/quota/model; file incomplete không được ghi. |

## 17. Validation Commands

Các lệnh kiểm tra local không gọi endpoint, không gọi Gemini và không gọi Kaggle:

```bash
python3 -m compileall app
python3 -c "from app.main import app; print(app.title)"
python3 scripts/check_kaggle_cutline_ready.py
```

Readiness script chỉ kiểm tra env, requirements và kernel source. Nó không push dataset/kernel và không chạy OCR.

## 18. Bảo Mật

- Không commit `app/core/config.env`.
- Không commit `kaggle.json`.
- Không hard-code Gemini API key hoặc Kaggle API key trong source code.
- Không log secret value.
- Chỉ log tên biến môi trường bị thiếu.
- Cutline chỉ upload package tối thiểu cho chunk được chọn:

```text
page.png
run_request.json
dataset-metadata.json
```

Không upload:

```text
workspace/
original.pdf
lesson/doc/{lesson_name}.pdf
chunk khác
lesson khác
```

## 19. Giới Hạn Hiện Tại

- Workflow hiện tại là debug/review-first, chưa phải production import pipeline.
- `/cutline/full` chỉ xử lý một selected lesson, không xử lý toàn bộ lessons.
- Không có global batch all-jobs workflow.
- Không có MongoDB/MinIO/PostgreSQL/Neo4j import.
- Không có database sync.
- Kaggle cutline yêu cầu Kaggle config hợp lệ.
- Gemini extraction có thể fail vì quota, model issue hoặc key cooldown.
- Raw debug JSON như `topic_raw.json` và `lesson_raw.json` phục vụ debug nội bộ, không nên phụ thuộc như stable public contract.
