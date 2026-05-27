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
- Extract keyword cho từng chunk từ lesson/chunk PDF đã finalized.

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
-> Review/edit/approve chunks
-> Finalize chunks cho một lesson
-> Extract keywords cho từng chunk cần xử lý
-> Review/edit/approve keywords
```

Chunk finalize chỉ rebuild finalized chunk PDFs. Keywords được tạo bằng route keyword riêng cho từng chunk, rồi review/edit/approve qua keyword review routes.

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

POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/extract
GET  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/approve
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/finalize

POST /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}/chunk/{chunk_name}/extract
GET  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}/approve

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

## 9. Chunk Review Workflow

Normal chunk flow for one selected lesson:

```text
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/extract
GET  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/approve
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/finalize
```

`extract` calls Gemini for one lesson PDF, writes reviewable `chunk_*.json`, and creates initial page-range PDFs in `chunk/{lesson_name}/doc/`. `GET` returns the current review list with `status="reviewing_chunks"`. `PUT` validates edited chunks, rewrites `chunk_*.json`, removes stale chunk JSON/PDF files if the count shrinks, and rebuilds initial page-range PDFs only. `PUT` does not call Kaggle or extract keywords.

Chunk validation keeps names sequential (`chunk_01`, `chunk_02`, ...), requires `start <= end`, requires `chunk_01.first_chunk=true` with no `content_head`, requires `chunk_02+` to have `content_head=true/false` with no `first_chunk`, and preserves numeric or Roman headings such as `1.`, `2.`, `I.`, `II.`.

If Gemini finds no valid top-level heading, extraction creates exactly one no-heading chunk for the whole lesson:

```json
{
  "name": "chunk_01",
  "start": 1,
  "end": 5,
  "heading": null,
  "title": "KHÔNG CÓ MỤC CHÍNH"
}
```

This no-heading chunk must not contain `first_chunk`, `content_head`, or `fallback_chunk`. Its initial `doc/chunk_01.pdf` is the full lesson PDF.

`approve` writes:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/chunks_approved.json
```

with:

```json
{
  "job_id": "...",
  "lesson_name": "lesson_01",
  "status": "approved_chunks",
  "chunks": []
}
```

`finalize` requires approved chunks. It sends all required real-heading cutline pages for the selected lesson to Kaggle in one batch run and rebuilds all official chunk PDFs in one pass from `lesson/doc/{lesson_name}.pdf`. It does not extract keywords. If the only chunk has `heading=null`, finalize skips Kaggle/cutline and rebuilds `doc/chunk_01.pdf` as the full lesson PDF.

Finalize response includes:

```json
{
  "job_id": "...",
  "lesson_name": "lesson_01",
  "status": "completed",
  "kaggle_mode": "batch",
  "kaggle_runs": 1,
  "processed_chunks": ["chunk_01", "chunk_03"],
  "skipped_chunks": [{"chunk_name": "chunk_02", "reason": "content_head=false"}],
  "failed_chunks": [],
  "updated_pdfs": ["chunk_01.pdf", "chunk_02.pdf", "chunk_03.pdf"],
  "debug_summary_path": ".../debug/lesson_cutline_full.json"
}
```

For a no-heading lesson, finalize summary has `processed_chunks: []`, `skipped_chunks: [{"chunk_name": "chunk_01", "reason": "heading=null; no cutline needed"}]`, and `updated_pdfs: ["chunk_01.pdf"]`.

## 12. Keyword Review Theo Lesson

Keywords are extracted per chunk after `/chunks/lesson/{lesson_name}/finalize` has rebuilt official chunk PDFs.

Public keyword routes:

```text
POST /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}/chunk/{chunk_name}/extract
GET  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}/approve
```

`POST /chunk/{chunk_name}/extract` extracts exactly one chunk and overwrites only that chunk's keyword file after exact-count extraction succeeds. The service writes a temporary file first and replaces `keyword_chunk_*.json` only after success. If Gemini still cannot return the exact count after completion attempts, the route returns an error and leaves any existing keyword file unchanged.

`GET` reads existing `keyword_chunk_*.json` files and returns `status="reviewing_keywords"` or `status="approved_keywords"` if `keywords_approved.json` exists and no chunks are missing. If some chunk keyword files do not exist yet, response includes `missing_chunks`.

`PUT` overwrites reviewed keyword files after validation. `POST /approve` validates existing keyword files and writes:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keywords_approved.json
```

Rules:

- Nếu lesson có đúng một chunk, bao gồm no-heading chunk:
  - Source PDF: `workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf`
  - Bắt buộc đúng 10 keywords.
  - Output: `workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keyword_chunk_01.json`

- Nếu lesson có nhiều chunk:
  - Source PDFs: `workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_*.pdf`
  - Bắt buộc đúng 5 keywords cho mỗi chunk.
  - Output: `workspace/outputs/{job_id}/chunk/{lesson_name}/keyword/keyword_chunk_*.json`

GET response:

```json
{
  "job_id": "3ce9f3cf-3a3a-4c49-b908-fabb50567db1",
  "lesson_name": "lesson_01",
  "status": "reviewing_keywords",
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

Review validation strips whitespace, rejects empty keyword names, rejects duplicate keyword names within the same chunk case-insensitively, and rejects unsupported keyword object fields such as `reason`, `confidence`, `source_type`, or `source_pdf`. Keyword extraction never writes incomplete keyword files.

Không tạo:

```text
workspace/outputs/{job_id}/keyword/{lesson_name}/
keywords_summary.json
*_keywords_raw.json
```

Keyword JSON không chứa `reason`, `confidence`, `source_type`, `source_name`, `source_pdf`, `lesson_name` hoặc `lesson_title`.

## 13. Workspace Output Tổng Hợp

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
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/extract
```

9. Review/edit/approve chunks:

```text
GET  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/approve
```

10. Finalize chunks, rebuild cutlines và auto extract keywords:

```text
POST /api/extract/jobs/{job_id}/chunks/lesson/{lesson_name}/finalize
```

11. Review/edit/approve keywords:

```text
GET  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
PUT  /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}
POST /api/extract/jobs/{job_id}/keywords/lesson/{lesson_name}/approve
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
Finalize cutline chỉ upload package tối thiểu cho required real-heading cutlines của selected lesson:

```text
pages/{chunk_name}.png
run_request.json
dataset-metadata.json
```

Không upload:

```text
workspace/
original.pdf
lesson/doc/{lesson_name}.pdf
lesson khác
```

## 19. Giới Hạn Hiện Tại

- Workflow hiện tại là debug/review-first, chưa phải production import pipeline.
- `/chunks/lesson/{lesson_name}/finalize` chỉ xử lý một selected lesson, không xử lý toàn bộ lessons.
- Không có global batch all-jobs workflow.
- Không có MongoDB/MinIO/PostgreSQL/Neo4j import.
- Không có database sync.
- Kaggle cutline yêu cầu Kaggle config hợp lệ.
- Gemini extraction có thể fail vì quota, model issue hoặc key cooldown.
- Raw debug JSON như `topic_raw.json` và `lesson_raw.json` phục vụ debug nội bộ, không nên phụ thuộc như stable public contract.
