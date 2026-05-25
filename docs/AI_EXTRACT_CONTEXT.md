# AI-Extract - Context dự án

## 1. Tổng quan hiện tại

AI-Extract là dịch vụ FastAPI nhẹ để xử lý PDF sách giáo khoa theo workflow review-first:

1. Upload PDF và tạo `job_id`.
2. Dùng Gemini để trích xuất cấu trúc Topic/Lesson từ trang mục lục hoặc phần đầu sách.
3. Tính range trang in, detect offset bằng OCR, rồi normalize sang trang PDF thật.
4. Cắt `original.pdf` thành PDF theo topic/lesson.
5. Cho phép review/chỉnh sửa JSON bằng API.
6. Approve topics trước, sau đó build và approve lessons.

AI-Extract được tách khỏi backend luận văn đầy đủ trong `FastAPI-Khoa-Luan`. Repository này không phụ trách database sync, UI review, batch chunk extraction, MinIO, MongoDB, PostgreSQL, Neo4j hoặc heavy import/sync. Kaggle/PaddleOCR hiện chỉ được dùng ở endpoint debug cutline cho một chunk, chưa phải batch pipeline.

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

Batch chunk extraction chưa được implement. Khi bổ sung sau này, chunk extraction nên chạy trên:

```text
workspace/outputs/{job_id}/lesson/doc/*.pdf
```

Không nên chạy chunk extraction trên `front_matter.pdf`, vì file này chỉ phục vụ Gemini đọc mục lục/phần đầu sách để lấy cấu trúc Topic/Lesson.

### Chunk debug extraction

Endpoint debug-only hiện có:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}
```

Mục tiêu: test chất lượng chunk extraction trên đúng một lesson PDF trước khi triển khai batch extraction.

Prompt chunk debug nằm trực tiếp trong Python builder:

```text
app/pipeline/gemini_extract/prompts/chunk_prompt.py
```

`chunk_debug_service.py` gọi `build_chunk_prompt_start_head(...)` từ file này trước khi gọi Gemini. Không dùng `prompts/templates/` cho chunk prompt.

Input:

```text
workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf
workspace/outputs/{job_id}/lesson/lessons_approved.json
```

Behavior:

- Validate job tồn tại.
- Require `lessons_approved.json`.
- Tìm lesson theo `lesson_name`.
- Gọi Gemini với đúng một lesson PDF.
- Gemini chỉ trả `name`, `start`, `first_chunk` hoặc `content_head`, `heading`, `title`.
- Normalize chunk names cục bộ: `chunk_01`, `chunk_02`, ...
- Tính `end` theo `start` của chunk kế tiếp và `content_head`.
- Split chunk PDFs từ `lesson/doc/{lesson_name}.pdf`.
- Không update `job.json` status.
- Không tạo `chunk/chunks.json`.
- Không tạo `chunk/chunks_approved.json`.

Output debug theo từng lesson:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/
  chunk_01.json
  chunk_02.json
  doc/
    chunk_01.pdf
    chunk_02.pdf
```

Mỗi chunk JSON là schema tối thiểu, không chứa lesson/topic metadata vì folder path đã xác định lesson:

```json
{
  "name": "chunk_01",
  "start": 1,
  "end": 3,
  "first_chunk": true,
  "heading": "1.",
  "title": "MỆNH ĐỀ"
}
```

```json
{
  "name": "chunk_02",
  "start": 4,
  "end": 6,
  "content_head": true,
  "heading": "2.",
  "title": "TẬP HỢP"
}
```

Quy tắc:

- `chunk_01` có `first_chunk: true`, không có `content_head`.
- `chunk_02` trở đi có `content_head: true/false`, không có `first_chunk`.
- `content_head=true`: cùng trang `start` vẫn có nội dung chunk trước nằm phía trên heading này.
- `content_head=false`: heading bắt đầu sạch ở đầu vùng nội dung.
- Với chunk hiện tại và chunk kế tiếp:
  - nếu `next_chunk.content_head=true`, `current.end = next_chunk.start`;
  - nếu `next_chunk.content_head=false`, `current.end = next_chunk.start - 1`.
- Chunk cuối có `end = total_pages_of_lesson_pdf`.

Endpoint này chỉ dùng để tune prompt và kiểm tra chất lượng chunk extraction an toàn trước khi có batch flow.

### Chunk cutline debug cho một chunk

Stage A tái dùng ý tưởng cũ từ `FastAPI-Khoa-Luan/gemini_pipeline`: dùng Kaggle/PaddleOCR để tìm bbox/dòng OCR của heading chunk và tính `y_cut`. Endpoint này chỉ xử lý đúng một chunk được chọn.

Endpoint:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline
```

Input bắt buộc:

```text
workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf
workspace/outputs/{job_id}/chunk/{lesson_name}/{chunk_name}.json
```

Chunk JSON phải có:

```json
{
  "name": "chunk_03",
  "start": 10,
  "end": 12,
  "content_head": true,
  "heading": "3.",
  "title": "MỐI QUAN HỆ GIỮA TĂNG TRƯỞNG KINH TẾ VÀ PHÁT TRIỂN BỀN VỮNG"
}
```

Behavior:

- Validate job tồn tại.
- Validate lesson PDF tồn tại.
- Validate chunk JSON tồn tại và có `start`, `heading`, `title`.
- Render đúng trang `chunk.start` từ lesson PDF thành PNG, với page number 1-based bên trong lesson PDF.
- Tạo package debug nhỏ gồm `page.png` và `run_request.json`.
- Gửi package này qua adapter Kaggle debug-only.
- Kaggle kernel/command chạy PaddleOCR, group OCR boxes thành dòng, match `heading` + `title`, rồi ghi output JSON/ảnh bbox.
- Backend đọc output Kaggle và copy artifact về workspace.
- Không sửa `chunk/{lesson_name}/{chunk_name}.json`.
- Không sửa `chunk/{lesson_name}/doc/{chunk_name}.pdf`.
- Không update `job.json` status.
- Backend AI-Extract không import hoặc chạy `paddleocr`/`paddlepaddle` local.
- Nếu Kaggle chưa được cấu hình, endpoint trả lỗi cấu hình rõ ràng, không yêu cầu cài PaddleOCR local.

Kaggle adapter hiện được implement trong:

```text
app/services/kaggle_cutline_debug_service.py
```

Backend tạo dataset package nhỏ gồm:

```text
page.png
run_request.json
dataset-metadata.json
```

Sau đó backend ghi kernel package tạm từ source kernel tối thiểu:

```text
app/pipeline/kaggle_kernels/debug-cutline-one-chunk/script.py
```

Adapter dùng Kaggle CLI/API flow tương tự project cũ:

- `kaggle datasets version` hoặc `kaggle datasets create` cho package một trang.
- `kaggle kernels push` để trigger kernel PaddleOCR.
- Poll `kaggle kernels status`.
- `kaggle kernels output` để tải output.
- Validate `request_id` trong `current_run_status_{request_id}.json` và `cutline_result.json` để tránh stale output.

Env cần cấu hình:

```text
AI_EXTRACT_KAGGLE_USERNAME
AI_EXTRACT_KAGGLE_KEY
AI_EXTRACT_KAGGLE_DATASET_SLUG
AI_EXTRACT_KAGGLE_KERNEL_REF
AI_EXTRACT_KAGGLE_WORK_DIR
AI_EXTRACT_KAGGLE_POLL_SECONDS
AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS
```

`AI_EXTRACT_KAGGLE_WORK_DIR`, `AI_EXTRACT_KAGGLE_POLL_SECONDS`, `AI_EXTRACT_KAGGLE_TIMEOUT_SECONDS` là optional. Nếu thiếu config bắt buộc, endpoint trả `503`.

Output debug-only:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}_cutline.json
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}_page.png
workspace/outputs/{job_id}/chunk/{lesson_name}/debug/{chunk_name}_bbox.png
```

Response slim:

```json
{
  "job_id": "...",
  "lesson_name": "lesson_01",
  "chunk_name": "chunk_03",
  "matched": true,
  "page_number": 10,
  "heading": "3.",
  "title": "...",
  "matched_text": "3. ...",
  "bbox": [120, 345, 980, 390],
  "y_cut": 345,
  "debug_json_path": "...",
  "debug_page_path": "...",
  "debug_bbox_path": "..."
}
```

Nếu không match, endpoint vẫn ghi debug JSON/ảnh và trả `matched=false` với reason nếu Kaggle output hợp lệ. Đây chỉ là Stage A để quan sát cutline; bước sau mới quyết định có áp dụng `y_cut` để recut PDF hay không.

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
- Thêm debug-only chunk endpoint cho một lesson: `POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}`.
- Debug chunk endpoint hiện ghi minimal JSON theo `chunk/{lesson_name}/chunk_01.json` và split chunk PDF từ `lesson/doc/{lesson_name}.pdf` sang `chunk/{lesson_name}/doc/chunk_01.pdf`.
- Chunk JSON không chứa lesson/topic metadata; folder path xác định lesson.
- Thêm rule `first_chunk` cho chunk đầu, `content_head` cho các chunk sau, và end calculation dựa trên start của chunk kế tiếp.
- Giữ prompt chunk debug trực tiếp trong `app/pipeline/gemini_extract/prompts/chunk_prompt.py`; không dùng template file.
- Debug chunk endpoint không update job status, không tạo batch `chunks.json`, không approve chunks và không implement batch extraction.
- Thêm Stage A cutline debug endpoint cho đúng một chunk: `POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}/chunk/{chunk_name}/cutline`.
- Cutline debug được chỉnh để dùng Kaggle/PaddleOCR thay vì yêu cầu PaddleOCR local trong backend.
- Backend chỉ render trang `chunk.start` thành PNG, tạo `run_request.json`, tự build/push Kaggle dataset/kernel debug-only và đọc output.
- Loại bỏ `paddleocr` khỏi backend requirements; AI-Extract backend không import/call PaddleOCR local.
- Thay placeholder `AI_EXTRACT_KAGGLE_CUTLINE_COMMAND` bằng adapter Kaggle thật dựa trên dataset/kernel/status/output flow của project cũ.
- Cutline debug không sửa chunk JSON, không sửa chunk PDF, không update job status và không implement batch cutline processing.
- Cập nhật tài liệu cho workflow Topic/Lesson extraction hiện tại:
  - `front_matter.pdf` chỉ dùng làm Gemini input để lấy cấu trúc sách.
  - `original.pdf` là nguồn cắt final topic/lesson PDFs.
  - OCR offset formula và default strategy đã được mô tả rõ.
  - `/lessons/build` được mô tả là build reviewable lessons từ approved topics + raw lessons.
  - Loại bỏ mô tả lỗi thời về skeleton extraction, public stub behavior và Gemini offset verification default.
