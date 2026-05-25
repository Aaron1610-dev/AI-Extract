# TOPIC_EXTRACTION_ADAPT_PLAN.md

## 1. Mục tiêu tài liệu

Tài liệu này mô tả hiện trạng Topic/Lesson extraction trong AI-Extract sau khi đã chuyển sang real Gemini topic runner, TOC/front-matter-first strategy và OCR offset detection.

Đây không còn là mô tả stub. Public Topic extract API hiện gọi Gemini thật. Lesson build API vẫn không gọi Gemini; nó build review data từ approved topics và raw lessons.

## 2. Gemini client hiện tại

File chính:

```text
app/services/gemini/client.py
```

Năng lực hiện có:

- `generate_text(...)`: text-only generation, vẫn phục vụ keyword APIs.
- `generate_with_pdf(prompt, pdf_path, model=None, mime_type="application/pdf", ...)`: upload/attach PDF và gọi Gemini.
- `GeminiRotationPool`: key rotation/cooldown.
- `get_gemini_rotation_status()`: debug rotation status.

Topic extraction dùng `generate_with_pdf(...)` thông qua:

```text
app/pipeline/gemini_extract/topic_runner.py
```

## 3. Prompt organization

Prompt cũ ở `app/pipeline/gemini_extract/prompts.py` đã được bỏ. Prompt hiện nằm trong package:

```text
app/pipeline/gemini_extract/prompts/
  __init__.py
  topic_lesson_prompt.py
```

Hàm prompt:

```text
build_topic_lesson_prompt()
```

Path:

```text
app/pipeline/gemini_extract/prompts/topic_lesson_prompt.py
```

Prompt hiện nhắm vào PDF chứa mục lục/phần đầu sách. Nó yêu cầu Gemini:

- Chỉ trả JSON hợp lệ.
- Trích xuất `topics` và `lessons`.
- Ưu tiên `start_printed`.
- Không bắt Gemini tự đoán `end_printed`.
- Giữ tiếng Việt, dấu và capitalization nếu có thể.

`end_printed` được code tính sau để giảm hallucination.

## 4. Front-matter-first extraction

Topic runner không gửi full textbook PDF cho Gemini ngay từ đầu nếu có thể tránh.

Flow hiện tại:

```text
original.pdf
-> create front_matter.pdf
-> Gemini reads front_matter.pdf
-> parse topics/lessons
-> fallback to original.pdf only if front_matter extraction fails
```

`front_matter.pdf` được tạo bởi:

```text
create_front_matter_pdf(...)
```

File:

```text
app/pipeline/gemini_extract/pdf_utils.py
```

Default range hiện tại:

```text
start_page = 1
end_page = 12
```

Nếu mục lục xuất hiện muộn hơn trong sách, nên tăng lên `1..20`. Range này chỉ dùng để tạo input nhỏ cho Gemini đọc cấu trúc sách. Nó không phải nguồn cắt final topic/lesson PDFs.

Final split vẫn dùng:

```text
workspace/uploads/{job_id}/original.pdf
```

## 5. Topic runner hiện tại

File:

```text
app/pipeline/gemini_extract/topic_runner.py
```

Hàm chính:

```text
run_topic_extraction(
    pdf_path,
    model=None,
    offset="auto",
    split_pdf=False,
    output_root=None,
    auto_detect_offset=True,
    offset_detection_min_confidence=0.65,
    use_front_matter=True,
    front_matter_start_page=1,
    front_matter_end_page=12,
    fallback_to_full_pdf=True,
)
```

Runner làm các việc sau:

1. Validate PDF.
2. Đếm tổng số trang bằng `count_pdf_pages(...)`.
3. Tạo `front_matter.pdf` nếu `use_front_matter=True`.
4. Gọi Gemini bằng `generate_with_pdf(...)` với `front_matter.pdf`.
5. Fallback sang full `original.pdf` nếu front-matter extraction fail hoặc không có structure.
6. Parse JSON bằng `parse_json_loose(...)`.
7. Normalize bằng `normalize_topic_lesson_payload(...)`.
8. Detect offset bằng OCR nếu `offset="auto"`.
9. Nếu `split_pdf=True`, split `original.pdf` vào `topic/doc/` và `lesson/doc/`.

Return có các field quan trọng:

```json
{
  "source": "gemini",
  "pdf_path": "...",
  "total_pdf_pages": 123,
  "extraction_input": "front_matter",
  "front_matter_pdf_path": ".../topic/front_matter.pdf",
  "fallback_used": false,
  "offset": 1,
  "offset_detection": {},
  "topics": [],
  "lessons": [],
  "raw_response_text": "...",
  "raw_payload": {},
  "split_result": {}
}
```

## 6. Parser và end_printed computation

File:

```text
app/pipeline/gemini_extract/topic_parser.py
```

Hàm chính:

- `parse_json_loose(text)`: parse JSON response từ Gemini, kể cả khi response có markdown fence hoặc text thừa.
- `normalize_topic_lesson_payload(payload, total_pdf_pages=None, offset=None)`: chuẩn hóa topics/lessons.
- `fill_end_printed_from_starts(topics, lessons, printed_end_of_main=None)`: tính `end_printed`.

Ví dụ:

```text
topic_01.start_printed = 5
topic_02.start_printed = 32
=> topic_01.end_printed = 31
```

```text
lesson_01.start_printed = 5
lesson_02.start_printed = 10
=> lesson_01.end_printed = 9
```

Sau khi có offset:

```text
start = start_printed + offset
end = end_printed + offset
```

Ví dụ:

```text
start_printed = 5
end_printed = 31
offset = 1
=> start = 6
=> end = 32
```

## 7. OCR offset detection

Gemini không được dùng để verify offset trong default path.

File:

```text
app/pipeline/gemini_extract/offset_detector.py
```

Hàm chính:

```text
detect_page_offset_by_bottom_ocr(...)
```

Wrapper runner đang dùng:

```text
detect_page_offset(...)
```

Default strategy:

```text
bottom_ocr_cumulative_vote
```

Default OCR settings:

- `anchor_page=28`
- `pages_per_round=3`
- `min_majority=2`
- `crop_px=250`
- `max_abs_offset=5`

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

Tesseract binary cần được cài ở OS level. Ví dụ macOS:

```bash
brew install tesseract
```

## 8. PDF utilities

File:

```text
app/pipeline/gemini_extract/pdf_utils.py
```

Các helper chính:

- `count_pdf_pages(...)`
- `printed_to_pdf_page(...)`
- `clamp_page_range(...)`
- `split_pdf_range(...)`
- `create_front_matter_pdf(...)`
- `split_topics_and_lessons(...)`

`split_topics_and_lessons(...)` ghi:

```text
workspace/outputs/{job_id}/topic/doc/{topic_name}.pdf
workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf
```

Các PDF này được cắt từ `original.pdf`, không phải từ `front_matter.pdf`.

## 9. Topic API integration

Endpoint public:

```text
POST /api/extract/jobs/{job_id}/topics/extract?offset=auto&split_pdf=true
```

Behavior hiện tại:

- Gọi real Gemini topic runner.
- Không dùng public stub.
- Không có `engine=stub`.
- `offset=auto` dùng OCR.
- `split_pdf=true` là default.
- Gemini đọc `topic/front_matter.pdf` trước.
- Full PDF là fallback nếu front-matter extraction fail.

Output chính:

```text
workspace/outputs/{job_id}/topic/front_matter.pdf
workspace/outputs/{job_id}/topic/topic_raw.json
workspace/outputs/{job_id}/topic/topics.json
workspace/outputs/{job_id}/lesson/lesson_raw.json
workspace/outputs/{job_id}/topic/doc/*.pdf
workspace/outputs/{job_id}/lesson/doc/*.pdf
```

`topic/topic_raw.json` chứa debug/raw artifact, gồm `extraction_input`, `front_matter_pdf_path`, `fallback_used`, `offset_detection`, `offset`, `raw_response_text`, `raw_payload`, `topics`, `lessons` và `split_result`.

## 10. Lesson build integration

Lesson endpoint hiện tại:

```text
POST /api/extract/jobs/{job_id}/lessons/build
```

Endpoint này không gọi Gemini. Nó build `lessons.json` từ:

```text
workspace/outputs/{job_id}/topic/topics_approved.json
workspace/outputs/{job_id}/lesson/lesson_raw.json
```

Mapping rule:

```text
lesson.end >= topic.start
lesson.start <= topic.end
```

Sau đó lesson được clamp vào topic range và thêm metadata:

- `topic_name`
- `topic_title`

## 11. Manual test

Chạy runner thủ công khi đã có Gemini key:

```bash
python3 -m app.pipeline.gemini_extract.topic_runner \
  --pdf workspace/uploads/{job_id}/original.pdf \
  --output-root workspace/outputs/{job_id} \
  --offset auto \
  --split-pdf
```

Command này gọi Gemini thật.

Manual API flow:

```text
POST /api/extract/jobs
POST /api/extract/jobs/{job_id}/topics/extract?offset=auto&split_pdf=true
GET  /api/extract/jobs/{job_id}/topics
PUT  /api/extract/jobs/{job_id}/topics
POST /api/extract/jobs/{job_id}/topics/approve
POST /api/extract/jobs/{job_id}/lessons/build
GET  /api/extract/jobs/{job_id}/lessons
PUT  /api/extract/jobs/{job_id}/lessons
POST /api/extract/jobs/{job_id}/lessons/approve
```

## 12. Rủi ro và điểm cần theo dõi

- Chất lượng OCR offset phụ thuộc Tesseract và vị trí số trang in.
- Nếu mục lục nằm sau trang 12, cần tăng front-matter range lên `1..20`.
- Gemini output có thể không ổn định; parser loose và normalizer giúp giảm lỗi nhưng vẫn cần test nhiều sách.
- `front_matter.pdf` chỉ phù hợp cho structure extraction, không dùng cho chunk hoặc final splitting.
- Chunk extraction chưa được implement; nếu làm sau này nên chạy trên `lesson/doc/*.pdf`.

## 13. Kết luận

Topic extraction hiện đã triển khai thật theo hướng:

```text
front_matter PDF -> Gemini structure extraction -> code-computed end_printed -> OCR offset -> split original PDF
```

Gemini riêng cho Lesson không thuộc workflow hiện tại. Endpoint `/lessons/build` chỉ build reviewable lessons từ approved topics và raw lessons của Topic stage.
