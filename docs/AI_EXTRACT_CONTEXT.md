# AI-Extract - Context dự án

## 1. Tổng quan hiện tại

AI-Extract là dịch vụ FastAPI nhẹ để xử lý PDF sách giáo khoa theo workflow review-first:

1. Upload PDF và tạo `job_id`.
2. Dùng Gemini để trích xuất cấu trúc Topic/Lesson từ trang mục lục hoặc phần đầu sách.
3. Tính range trang in, detect offset bằng OCR, rồi normalize sang trang PDF thật.
4. Cắt `original.pdf` thành PDF theo topic/lesson.
5. Cho phép review/chỉnh sửa JSON bằng API.
6. Approve topics trước, sau đó build và approve lessons.

AI-Extract được tách khỏi backend luận văn đầy đủ trong `FastAPI-Khoa-Luan`. Repository này không phụ trách database sync, UI review, chunk extraction, Kaggle OCR/cutline, MinIO, MongoDB, PostgreSQL, Neo4j hoặc heavy import/sync.

## 2. Kiến trúc source code

- `app/main.py`: FastAPI entry, include các route health/debug/keyword/extraction.
- `app/api/routes/`: HTTP route layer.
- `app/services/gemini/`: Gemini client, key rotation và keyword service hiện có.
- `app/services/extraction/`: orchestration theo job cho topic, lesson và status.
- `app/services/storage/workspace_service.py`: quản lý workspace theo `job_id`, path và JSON I/O.
- `app/pipeline/gemini_extract/`: helper pipeline cho Topic/Lesson extraction.
- `app/pipeline/gemini_extract/prompts/`: prompt package cho Gemini extraction.
- `workspace/uploads/`: PDF upload theo job.
- `workspace/outputs/`: artifact JSON/PDF theo job.

## 3. Workspace output hiện tại

```text
workspace/
  uploads/
    {job_id}/
      original.pdf

  outputs/
    {job_id}/
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
```

`front_matter.pdf` chỉ là input nhỏ cho Gemini đọc mục lục/phần đầu sách. Các file trong `topic/doc/` và `lesson/doc/` được cắt từ `original.pdf`, không cắt từ `front_matter.pdf`.

## 4. API hiện tại

### Upload job

```text
POST /api/extract/jobs
GET  /api/extract/jobs/{job_id}
```

`POST /api/extract/jobs` nhận PDF upload qua `multipart/form-data`, field `file`, tạo `job_id`, lưu:

- `workspace/uploads/{job_id}/original.pdf`
- `workspace/outputs/{job_id}/job.json`

Status ban đầu:

```text
uploaded
```

### Topic extraction và review

```text
POST /api/extract/jobs/{job_id}/topics/extract?offset=auto&split_pdf=true
GET  /api/extract/jobs/{job_id}/topics
PUT  /api/extract/jobs/{job_id}/topics
POST /api/extract/jobs/{job_id}/topics/approve
```

`POST /topics/extract` hiện gọi real Gemini topic runner. Public stub extraction không còn được dùng và không có `engine=stub` mode.

Query params:

- `offset`: mặc định `auto`; nhận `auto`, `none`, hoặc số nguyên dạng chuỗi như `0`, `1`, `4`.
- `split_pdf`: mặc định `true`.

Public response của endpoint này được giữ nhỏ để frontend/review dùng trực tiếp:

```json
{
  "job_id": "...",
  "status": "reviewing_topics",
  "offset": 2,
  "topics": [
    {
      "name": "topic_01",
      "start": 8,
      "end": 19,
      "heading": "CHỦ ĐỀ 1:",
      "title": "TĂNG TRƯỞNG VÀ PHÁT TRIỂN KINH TẾ"
    }
  ]
}
```

Các dữ liệu debug/internal như Gemini raw response, raw payload, offset detection chi tiết, split result, `front_matter_pdf_path`, `fallback_used` và internal paths không trả trong HTTP response. Chúng được lưu trong `topic/topic_raw.json`.

Approve topics tạo:

```text
workspace/outputs/{job_id}/topic/topics_approved.json
```

### Lesson build và review

```text
POST /api/extract/jobs/{job_id}/lessons/build
GET  /api/extract/jobs/{job_id}/lessons
PUT  /api/extract/jobs/{job_id}/lessons
POST /api/extract/jobs/{job_id}/lessons/approve
```

Endpoint cũ `POST /api/extract/jobs/{job_id}/lessons/extract` đã được đổi tên thành `/lessons/build` vì endpoint này không gọi Gemini và không extract lesson trực tiếp từ PDF.

`POST /lessons/build` build reviewable lessons từ:

- `workspace/outputs/{job_id}/topic/topics_approved.json`
- `workspace/outputs/{job_id}/lesson/lesson_raw.json`

`lesson_raw.json` là raw Gemini output nên có thể chứa cả các item mục lục không phải bài học thật, ví dụ `"Bài tập cuối chương I"` với `heading=null`. File raw này được giữ nguyên.

Khi build reviewable lessons, `/lessons/build` chỉ nhận các item có heading bài học đánh số hợp lệ, hiện match pattern case-insensitive:

```text
^\\s*Bài\\s+\\d+
```

Ví dụ hợp lệ:

- `Bài 1.`
- `Bài 2`
- `BÀI 3`
- `bài 4.`

Ví dụ bị loại khỏi `lessons.json`:

- `heading = null`
- `heading = ""`
- `Bài tập cuối chương I`
- `Ôn tập chương I`
- `Thực hành cuối chương`

Sau khi lọc, các lesson reviewable được sort theo `start/end` và renumber tuần tự `lesson_01`, `lesson_02`, `lesson_03`, ... Không tạo `lessons_skipped.json` và không expose skipped items trong API response.

Sau đó endpoint map valid lessons vào topics bằng page range overlap, ghi:

```text
workspace/outputs/{job_id}/lesson/lessons.json
```

Approve lessons tạo:

```text
workspace/outputs/{job_id}/lesson/lessons_approved.json
```

## 5. Topic extraction flow hiện tại

Flow chính:

```text
original.pdf
-> front_matter.pdf
-> Gemini extracts topics/lessons từ front_matter.pdf
-> code computes end_printed
-> OCR detects offset từ original.pdf
-> normalize start/end
-> split original.pdf into topic/doc and lesson/doc PDFs
```

Chi tiết:

1. Đọc `workspace/uploads/{job_id}/original.pdf`.
2. Tạo `workspace/outputs/{job_id}/topic/front_matter.pdf`.
3. Gọi Gemini bằng `generate_with_pdf(...)` với `front_matter.pdf`.
4. Nếu front-matter extraction lỗi hoặc không trả đủ structure, fallback sang full `original.pdf`.
5. Parse JSON bằng `parse_json_loose(...)`.
6. Normalize payload bằng `normalize_topic_lesson_payload(...)`.
7. Tính `end_printed` từ các `start_printed` liên tiếp.
8. Nếu `offset=auto`, detect offset bằng OCR bottom-crop cumulative voting.
9. Convert trang in sang trang PDF thật bằng offset.
10. Nếu `split_pdf=true`, cắt `original.pdf` vào `topic/doc/` và `lesson/doc/`.
11. Ghi artifact JSON và set status `reviewing_topics`.

## 6. Front matter PDF

`create_front_matter_pdf(...)` nằm trong:

```text
app/pipeline/gemini_extract/pdf_utils.py
```

Mặc định hiện tại cắt trang PDF thật `1..12` từ `original.pdf`.

Nếu mục lục của sách xuất hiện muộn hơn, nên tăng range lên `1..20` trong cấu hình hoặc tham số runner. Range 12 hoặc 20 trang này chỉ dùng để giảm input Gemini khi trích xuất cấu trúc sách, không ảnh hưởng đến nguồn cắt PDF cuối cùng.

## 7. Prompt organization

Prompt cũ `app/pipeline/gemini_extract/prompts.py` đã được bỏ. Prompt hiện nằm trong package:

```text
app/pipeline/gemini_extract/prompts/
  __init__.py
  topic_lesson_prompt.py
```

`build_topic_lesson_prompt()` hiện nằm trong:

```text
app/pipeline/gemini_extract/prompts/topic_lesson_prompt.py
```

Prompt hiện yêu cầu Gemini đọc các trang TOC/front-matter, trả JSON hợp lệ, ưu tiên `start_printed`, và không bắt Gemini tự đoán `end_printed`.

## 8. Tính end_printed

`normalize_topic_lesson_payload(...)` trong `app/pipeline/gemini_extract/topic_parser.py` gọi `fill_end_printed_from_starts(...)` để tính `end_printed` từ các `start_printed`.

Ví dụ topic:

```text
topic_01.start_printed = 5
topic_02.start_printed = 32
=> topic_01.end_printed = 31
```

Ví dụ lesson:

```text
lesson_01.start_printed = 5
lesson_02.start_printed = 10
=> lesson_01.end_printed = 9
```

Cách này giảm hallucination của LLM và giữ page range deterministic. Nếu topic/lesson cuối không có item kế tiếp, code dùng `printed_end_of_main` nếu Gemini phát hiện được; nếu không, fallback về range ngắn theo dữ liệu có sẵn.

## 9. OCR offset detection

`offset=auto` dùng OCR bottom-crop cumulative voting, không dùng Gemini verify offset trong default path.

File chính:

```text
app/pipeline/gemini_extract/offset_detector.py
```

Hàm chính:

```text
detect_page_offset_by_bottom_ocr(...)
```

Wrapper đang dùng bởi runner:

```text
detect_page_offset(...)
```

Default strategy:

```text
bottom_ocr_cumulative_vote
```

Công thức:

```text
offset = actual_page - printed_page
actual_page = printed_page + offset
```

Ví dụ:

```text
actual PDF page 30 có printed page 29
actual PDF page 31 có printed page 30
=> offset = 1
```

Sau đó:

```text
start = start_printed + offset
end = end_printed + offset
```

Default OCR behavior:

- Crop đáy trang khoảng `250px`.
- Kiểm tra nhiều trang theo kiểu cumulative voting.
- Nếu một offset đạt đủ số phiếu, trả offset đó.
- Tesseract binary phải được cài ở OS level.

Ví dụ macOS:

```bash
brew install tesseract
```

## 10. Topic output files

Sau `POST /topics/extract`, các file sau có thể được tạo:

```text
workspace/outputs/{job_id}/topic/front_matter.pdf
workspace/outputs/{job_id}/topic/topic_raw.json
workspace/outputs/{job_id}/topic/topics.json
workspace/outputs/{job_id}/lesson/lesson_raw.json
workspace/outputs/{job_id}/topic/doc/*.pdf
workspace/outputs/{job_id}/lesson/doc/*.pdf
```

Ý nghĩa:

- `topic_raw.json`: artifact debug/raw đầy đủ của Topic stage, gồm `source`, `extraction_input`, `front_matter_pdf_path`, `fallback_used`, `offset`, `offset_detection`, `raw_response_text`, `raw_payload`, `topics`, `lessons`, `split_result`.
- `topics.json`: danh sách topics để review/edit.
- `lesson_raw.json`: danh sách lessons thô do Topic stage trả về, dùng cho `/lessons/build`.
- `topic/doc/*.pdf` và `lesson/doc/*.pdf`: PDF cắt từ `original.pdf`.

## 11. Full workflow hiện tại

```text
POST /api/extract/jobs
-> save original.pdf
-> status = uploaded

POST /api/extract/jobs/{job_id}/topics/extract?offset=auto&split_pdf=true
-> create front_matter.pdf
-> Gemini extracts topics/lessons from front_matter.pdf
-> fallback to original.pdf only if needed
-> compute end_printed
-> OCR detects offset
-> normalize start/end
-> split original.pdf into topic/doc and lesson/doc
-> create topic_raw.json, topics.json, lesson_raw.json
-> return slim response: job_id, status, offset, topics
-> status = reviewing_topics

GET/PUT /api/extract/jobs/{job_id}/topics
-> review/edit topics

POST /api/extract/jobs/{job_id}/topics/approve
-> create topics_approved.json
-> status = topics_approved

POST /api/extract/jobs/{job_id}/lessons/build
-> build lessons.json from approved topics + lesson_raw
-> filter non-numbered/null-heading TOC items
-> renumber reviewable lessons sequentially
-> map each lesson to a topic
-> status = reviewing_lessons

GET/PUT /api/extract/jobs/{job_id}/lessons
-> review/edit lessons

POST /api/extract/jobs/{job_id}/lessons/approve
-> create lessons_approved.json
-> status = lessons_approved
```

## 12. Chunk note

Chunk extraction chưa được implement. Khi bổ sung sau này, chunk extraction nên chạy trên:

```text
workspace/outputs/{job_id}/lesson/doc/*.pdf
```

Không nên chạy chunk extraction trên `front_matter.pdf`, vì file này chỉ phục vụ Gemini đọc mục lục/phần đầu sách để lấy cấu trúc Topic/Lesson.

## 13. Scripts cleanup note

Production OCR offset logic hiện nằm trong:

```text
app/pipeline/gemini_extract/offset_detector.py
```

Các script thử nghiệm OCR/pixel nên được xem là temporary hoặc chuyển vào `scripts/experiments/`. Script test sạch có thể gọi trực tiếp `detect_page_offset_by_bottom_ocr(...)` thay vì copy logic OCR.

## 14. Quy tắc phát triển

- Không hard-code secret hoặc API key.
- Không đưa database/object storage vào AI-Extract nếu chưa có yêu cầu rõ.
- Không copy toàn bộ `gemini_pipeline`.
- Giữ API review-first file-based.
- Giữ runtime keyword APIs hiện có.
- Khi chỉnh extraction flow, cập nhật docs và Change Log trong file này.

## 15. Change Log / Context Updates

### 2026-05-25

- Tạo context ban đầu cho AI-Extract là FastAPI service nhẹ, tách khỏi backend luận văn đầy đủ.
- Refactor source structure thành route/service/schema/pipeline/storage layers.
- Implement job/workspace storage skeleton với `POST /api/extract/jobs` và `GET /api/extract/jobs/{job_id}`.
- Implement Topic review APIs, sau đó thay public Topic stub bằng real Gemini `topic_runner`.
- Implement Lesson review flow dạng build từ approved topics + raw lessons.
- Đổi lesson endpoint từ `/lessons/extract` sang `/lessons/build` vì endpoint này không gọi Gemini.
- Refactor output files vào `topic/` và `lesson/`.
- Thêm Gemini PDF-capable `generate_with_pdf(...)`.
- Thêm parser/normalizer, PDF split helpers, OCR offset detection và manual runner.
- Thay Gemini verify offset bằng OCR bottom-crop cumulative voting.
- Refactor prompts thành package `app/pipeline/gemini_extract/prompts/`.
- Chuyển Topic/Lesson structure extraction sang TOC/front-matter-first strategy.
- Thêm `topic/front_matter.pdf`.
- Thêm logic tính `end_printed` từ `start_printed`.
- Giữ full PDF extraction làm fallback.
- Simplify public Topic extraction response còn `job_id`, `status`, `offset`, `topics`.
- Giữ full debug/internal extraction data trong `topic/topic_raw.json`.
- Không đổi route path hoặc extraction behavior khi simplify response.
- Filter null/empty/non-numbered lesson headings trong `/lessons/build`.
- Giữ `lesson/lesson_raw.json` nguyên trạng, chỉ lọc output reviewable `lesson/lessons.json`.
- Renumber reviewable lessons tuần tự sau khi lọc; không tạo `lessons_skipped.json`.
- Cập nhật tài liệu cho workflow Topic/Lesson extraction hiện tại:
  - `front_matter.pdf` chỉ dùng làm Gemini input để lấy cấu trúc sách.
  - `original.pdf` là nguồn cắt final topic/lesson PDFs.
  - OCR offset formula và default strategy đã được mô tả rõ.
  - `/lessons/build` được mô tả là build reviewable lessons từ approved topics + raw lessons.
  - Loại bỏ mô tả lỗi thời về skeleton extraction, public stub behavior và Gemini offset verification default.
