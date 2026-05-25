# TOPIC_EXTRACTION_ADAPT_PLAN.md

## 1. Năng lực Gemini client hiện tại của AI-Extract

File đã kiểm tra:

- `app/services/gemini/client.py`
- `app/services/gemini/keyword_service.py`
- `app/pipeline/gemini_extract/topic_runner.py`
- `app/pipeline/gemini_extract/prompts.py`
- `app/pipeline/gemini_extract/pdf_utils.py`
- `app/pipeline/gemini_extract/topic_parser.py`
- `docs/GEMINI_PIPELINE_TOPIC_LESSON_CONTEXT.md`
- `docs/AI_EXTRACT_CONTEXT.md`

`app/services/gemini/client.py` hiện hỗ trợ:

- Text-only generation qua `generate_text(...)`.
- PDF-capable generation qua `generate_with_pdf(prompt, pdf_path, model=None, mime_type="application/pdf", ...)`.
- Key rotation qua `GeminiRotationPool`.
- Debug rotation status qua `get_gemini_rotation_status()`.

`generate_text(...)` vẫn giữ behavior cũ cho keyword APIs. `generate_with_pdf(...)` đã được thêm ở Step 4A, nhưng chưa được wire vào Topic extraction.

Dependency hiện có:

- `google-genai`: dùng cho PDF upload/generation.
- `pypdf`: dùng cho helper đếm trang và split PDF range.

## 2. Gap analysis cho PDF Topic extraction

Các helper nền đã có:

- Minimal Topic/Lesson prompt: `build_topic_lesson_prompt()`.
- Verify prompt cho offset sau này: `build_topic_verify_prompt(topic_label)`.
- Loose JSON parser: `parse_json_loose(...)`.
- Normalizer: `normalize_topic_lesson_payload(...)`.
- PDF page utilities:
  - `count_pdf_pages(...)`
  - `make_single_page_pdf(...)`
  - `printed_to_pdf_page(...)`
  - `clamp_page_range(...)`
  - `split_pdf_range(...)`
  - `split_topics_and_lessons(...)`
- Manual runner: `run_topic_extraction(...)`.
- Auto offset detector: `detect_page_offset(...)`.

`run_topic_extraction(...)` đã được implement để test thủ công. Runner này gọi `generate_with_pdf(...)`, parse JSON, có thể tự detect offset, normalize topics/lessons, và có thể split PDF nếu truyền `split_pdf=True`.

Các phần còn thiếu trước khi thay Topic stub:

- Manual test với một PDF sách thật.
- Service integration trong `topic_service.py`.

Auto offset detection đã được adapt từ `FastAPI-Khoa-Luan/gemini_pipeline`: tạo single-page verification PDFs quanh trang in bắt đầu của topic đầu tiên đáng tin cậy, hỏi Gemini bằng verify prompt, rồi tính `offset = actual_page - start_printed`.

Preview PDF creation vẫn cố ý chưa được implement trong AI-Extract. Auto offset detection dùng single-page PDF, không dùng preview PDF.

## 3. File tối thiểu cần implement sau

`app/pipeline/gemini_extract/topic_runner.py`

- Đã có `run_topic_extraction(...)` để gọi thủ công từ Python hoặc CLI.
- Runner nhận PDF gốc, gọi `count_pdf_pages(...)`, build prompt, gọi `generate_with_pdf(...)`, detect offset nếu `offset="auto"`, parse/normalize payload, và trả `topics`/`lessons`.
- Runner không ghi workspace, không update `job.json`, không update status.
- Nếu `split_pdf=True`, runner yêu cầu `output_root` và ghi PDF vào `topic/doc/` và `lesson/doc/`.

`app/pipeline/gemini_extract/offset_detector.py`

- Có `detect_page_offset(...)`.
- Dùng `make_single_page_pdf(...)`, `build_topic_verify_prompt(...)`, `generate_with_pdf(...)`, và `parse_json_loose(...)`.
- Reuse Gemini key rotation vì đi qua AI-Extract `generate_with_pdf(...)`.
- Chỉ dùng trong manual runner, chưa wire vào API.

`app/services/extraction/topic_service.py`

- Vẫn đang dùng Topic stub.
- Sau này mới thay stub bằng `topic_runner`.
- Vẫn chịu trách nhiệm job-level orchestration và ghi file workspace.

`app/pipeline/gemini_extract/pdf_utils.py`

- Đã có helper split PDF thật vào:
  - `topic/doc/`
  - `lesson/doc/`
- Chưa có preview PDF utility.

## 4. Flow Topic thật đề xuất

Flow đề xuất khi thay Topic stub:

1. Đọc PDF gốc:
   - `workspace/uploads/{job_id}/original.pdf`
2. Set job status:
   - `extracting_topics`
3. Đếm tổng số trang PDF bằng `count_pdf_pages(...)`.
4. Build prompt bằng `build_topic_lesson_prompt()`.
5. Gọi Gemini bằng `generate_with_pdf(...)`.
6. Parse response bằng `parse_json_loose(...)`.
7. Nếu `offset="auto"`, gọi `detect_page_offset(...)` trên topics parse lần đầu.
8. Normalize bằng `normalize_topic_lesson_payload(...)` với manual/detected offset.
9. Ghi full raw output:
   - `workspace/outputs/{job_id}/topic/topic_raw.json`
10. Ghi editable topic review list:
   - `workspace/outputs/{job_id}/topic/topics.json`
11. Ghi raw lesson source từ Topic stage:
   - `workspace/outputs/{job_id}/lesson/lesson_raw.json`
12. Nếu cần split PDF, dùng `split_topics_and_lessons(...)` để ghi:
   - `workspace/outputs/{job_id}/topic/doc/{topic_name}.pdf`
   - `workspace/outputs/{job_id}/lesson/doc/{lesson_name}.pdf`
13. Set job status:
   - `reviewing_topics`

Shape đề xuất cho `topic/topic_raw.json`:

```json
{
  "job_id": "...",
  "source": "gemini",
  "topics": [],
  "lessons": [],
  "raw_response": {}
}
```

`topic/topics.json` chỉ chứa mảng topics. `lesson/lesson_raw.json` chỉ chứa mảng lessons thô từ Topic stage.

## 5. Rủi ro và điểm chưa rõ

- Chưa gọi Gemini trong validation, nên `generate_with_pdf(...)` chưa được kiểm thử với PDF thật.
- Auto offset detection đã wire vào manual runner, nhưng chưa test với Gemini thật trong validation.
- Nếu bỏ offset verification ở bản đầu, page range có thể sai với sách có số trang in lệch so với trang PDF.
- Output JSON từ Gemini có thể không ổn định; cần test parser/normalizer với response thật.
- Preview PDF creation chưa implement theo yêu cầu Step 4B.
- Topic stage cũ trả cả topics và lessons. AI-Extract cần giữ điều này vì Lesson stage dựa vào `lesson/lesson_raw.json`.

## 6. Khuyến nghị bước code nhỏ nhất tiếp theo

Bước nhỏ nhất tiếp theo:

1. Chạy manual runner trên một PDF thật với `--offset auto`.
2. Kiểm tra `offset_detection.detected`, `offset`, và file PDF split ở `topic/doc/`, `lesson/doc/`.
3. Nếu kết quả ổn định, mới cân nhắc wire runner vào `topic_service.py`.

Topic API hiện vẫn dùng stub. Không có real Topic extraction nào được wire ở Step 4B.

## 7. Manual test runner

Runner có thể chạy thủ công sau khi đã cấu hình Gemini API key:

```bash
python3 -m app.pipeline.gemini_extract.topic_runner \
  --pdf workspace/uploads/{job_id}/original.pdf \
  --output-root workspace/outputs/{job_id} \
  --offset auto \
  --split-pdf
```

Hoặc truyền offset thủ công:

```bash
python3 -m app.pipeline.gemini_extract.topic_runner \
  --pdf workspace/uploads/{job_id}/original.pdf \
  --output-root workspace/outputs/{job_id} \
  --offset 4 \
  --split-pdf
```

Lưu ý:

- Command trên sẽ gọi Gemini thật.
- Không chạy command này trong validation tự động nếu chưa muốn gọi Gemini.
- Nếu dùng `--split-pdf`, output PDF sẽ nằm trong:
  - `workspace/outputs/{job_id}/topic/doc/`
  - `workspace/outputs/{job_id}/lesson/doc/`
- Topic API hiện vẫn dùng stub; runner chưa được wire vào route.
