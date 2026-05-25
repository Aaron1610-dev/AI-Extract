# GEMINI_PIPELINE_TOPIC_LESSON_CONTEXT.md

## 1. Mục tiêu tài liệu

Tài liệu này ghi lại cách `FastAPI-Khoa-Luan/gemini_pipeline` hiện đang trích xuất Topic và Lesson từ PDF sách giáo khoa. Mục tiêu là giúp các bước sau trong `AI-Extract` adapt đúng phần tối thiểu cần thiết, không copy toàn bộ pipeline nặng.

Phạm vi tài liệu chỉ dựa trên source đã inspect. Những điểm chưa thể xác nhận bằng đọc code được đánh dấu `Cần chạy thử để xác nhận`.

## 2. Tổng quan gemini_pipeline

`gemini_pipeline` là pipeline xử lý PDF sách giáo khoa trong backend luận văn lớn. Theo `gemini_pipeline/readme.md`, pipeline đầy đủ có thể:

- Đọc PDF sách trong `gemini_pipeline/Input/`.
- Gọi Gemini để tách cấu trúc sách.
- Tạo bundle trong `gemini_pipeline/Output/<pdf_stem>/`.
- Tạo PDF/JSON cho Topic, Lesson, Chunk.
- Chạy Kaggle postprocess và keyword extraction trong flow đầy đủ `scripts/auto_split.py`.
- Cho backend lớn import bundle qua admin/heavy stage.

Đối với `AI-Extract`, chỉ phần Topic và Lesson là liên quan. Các phần Chunk, Kaggle OCR/cutline, keyword extraction, import/sync database/object storage không nên đưa sang giai đoạn này.

Các file bắt buộc đã kiểm tra và đều tồn tại:

- `gemini_pipeline/scripts/light_extract_job.py`
- `gemini_pipeline/scripts/connect.py`
- `gemini_pipeline/sgk_extract/gemini_runner.py`
- `gemini_pipeline/sgk_extract/gemini_client.py`
- `gemini_pipeline/sgk_extract/pdf_output.py`
- `gemini_pipeline/sgk_extract/prompts.py`
- `gemini_pipeline/sgk_extract/chunk_pipeline.py`
- `gemini_pipeline/sgk_extract/chunk_postprocess.py`
- `gemini_pipeline/sgk_extract/les_top_pipeline.py`
- `gemini_pipeline/readme.md`
- `gemini_pipeline/scripts/auto_split.py`

## 3. Entry point hiện tại để chạy Topic/Lesson

Có hai entry point đáng chú ý.

### Review-first stage runner

File: `gemini_pipeline/scripts/light_extract_job.py`

Command được hỗ trợ bởi `argparse`:

```bash
cd FastAPI-Khoa-Luan/gemini_pipeline
python scripts/light_extract_job.py --workspace <workspace_path> --stage topics
python scripts/light_extract_job.py --workspace <workspace_path> --stage lessons
python scripts/light_extract_job.py --workspace <workspace_path> --stage chunks
```

`--stage` chỉ nhận một trong ba giá trị: `topics`, `lessons`, `chunks`.

`light_extract_job.py` đọc config từ:

```text
<workspace>/job_config.json
```

Shape thực tế quan sát trong `ReviewWorkspace/.../job_config.json`:

```json
{
  "job_id": "uuid",
  "source_pdf_path": "/absolute/path/to/source.pdf",
  "api_config": "/absolute/path/to/gemini_pipeline/config.env",
  "model": "gemini-2.5-flash"
}
```

Với `stage=topics`, script chạy `_run_topics(workspace, config)`.

Với `stage=lessons`, script chạy `_run_lessons(workspace, config)`.

Nếu lỗi, `light_extract_job.py` ghi:

- `<workspace>/progress.json` với `status="error"`.
- `<workspace>/result.json` với `{ "ok": false, "error": "...", "traceback": "..." }`.
- `<workspace>/<stage>.log`.

### Full standalone pipeline

File: `gemini_pipeline/scripts/auto_split.py`

README hướng dẫn:

```bash
cd FastAPI-Khoa-Luan/gemini_pipeline
python -m scripts.auto_split
```

`auto_split.py` dùng `run_extract_save_split(...)` từ `sgk_extract.les_top_pipeline`, sau đó chạy chunk, Kaggle và keyword. Flow này không phù hợp để copy nguyên sang `AI-Extract`, nhưng hữu ích để hiểu phần Topic/Lesson ban đầu.

### Config/API key

`scripts/connect.py` tạo `KeyManager` qua `get_key_manager(env_path, state_file=None)`.

`get_key_manager` gọi `load_gemini_key_config` từ backend lớn:

```python
from app.services.infrastructure.gemini_client import (
    get_gemini_rotation_state_file,
    load_gemini_key_config,
)
```

`sgk_extract/gemini_client.py` cũng phụ thuộc `app.services.infrastructure.gemini_client.GeminiRotationPool`.

Config file hiện dùng:

```text
gemini_pipeline/config.env
```

Các key/env cần có theo `requirements.txt` và code:

- `GEMINI_API_KEYS`
- `GEMINI_MIN_INTERVAL` nếu có.
- `GEMINI_COOLDOWN_SECONDS` nếu có.

Không ghi lại API key thật trong tài liệu này.

## 4. Luồng tách Topic

Entry point review-first:

- File: `gemini_pipeline/scripts/light_extract_job.py`
- Hàm: `_run_topics(workspace: Path, config: dict)`

Luồng thực tế:

1. Đọc PDF gốc từ `config["source_pdf_path"]`.
2. Đọc `api_config` từ config, default là `gemini_pipeline/config.env`.
3. Đọc model từ config, default `_DEFAULT_MODEL = "gemini-2.5-flash-lite"`.
4. Tạo `KeyManager` bằng `scripts.connect.get_key_manager(api_config, state_file=workspace / "gemini_rotation_state.json")`.
5. Đếm tổng số trang bằng `pypdf.PdfReader`.
6. Tạo preview PDF 20 trang đầu bằng `sgk_extract.les_top_pipeline._make_preview_first_pages(pdf_path, first_n_pages=20)`.
7. Build prompt bằng:
   - Prefix trong `_run_topics`: nhấn mạnh PDF chỉ là preview 20 trang đầu để đọc mục lục.
   - `sgk_extract.prompts.build_topic_lesson_prompt()`.
8. Gọi Gemini qua:
   - `sgk_extract.gemini_runner.extract_structure_from_pdf(...)`
   - `sgk_extract.gemini_client.GeminiPool.generate_with_pdf(...)`
   - `google.genai.Client.files.upload(...)`
   - `client.models.generate_content(...)`
9. Parse JSON bằng `sgk_extract.gemini_runner._parse_json_loose`.
10. Verify offset trang Topic bằng `sgk_extract.les_top_pipeline.verify_topics_and_get_offset(...)`.
11. `verify_topics_and_get_offset` lấy topic từ `list_topic`, dùng `start_printed + raw_offset` làm trang dự đoán, cắt từng trang đơn bằng `_make_single_page_pdf`, rồi gọi Gemini với `build_topic_verify_prompt(full_topic_label)`.
12. Sau khi có `final_offset`, gán `data["offset"] = final_offset`.
13. Chuẩn hóa manifest bằng `sgk_extract.pdf_output.normalize_manifest(data, total_pages=total_pages_full)`.
14. `normalize_manifest` đi vào `_normalize_from_start_printed` nếu có `offset`. Hàm này:
    - Đọc `printed_end_of_main`.
    - Flatten `list_topic` và `list_lesson` từ `start_printed`.
    - Sort theo số thứ tự và `start_printed`.
    - Tính `end_printed` của topic bằng start của topic kế tiếp, topic cuối bằng `printed_end_of_main - 1`.
    - Tính `end_printed` của lesson tương tự.
    - Convert printed page sang PDF page bằng `start_printed + offset`, `end_printed + offset`.
    - Rebuild về manifest `list_topic`, `list_lesson` có `start`, `end`, `heading`, `title`.
15. Ghi manifest và split PDF:
    - `prepare_workspace(pdf_path, output_root=unique_output_root)`
    - `save_manifest(base_dir, pdf_stem, data)`
    - `split_from_manifest(pdf_path, data, base_dir)`
16. Flatten topics bằng `_flatten(data.get("list_topic", []))`.
17. Flatten raw lessons bằng `_flatten(data.get("list_lesson", []))`.
18. Ghi `<workspace>/topics_partial.json`.
19. Ghi `<workspace>/extraction_state.json` gồm `bundle_path`, `book_stem`, `raw_lessons`.
20. Ghi `<workspace>/result.json` gồm `{ "ok": true, "bundle_path": "...", "topics": [...] }`.
21. Ghi `<workspace>/progress.json` với `status="reviewing_topics"`.

Output chính của Topic stage:

- `<workspace>/topics_partial.json`
- `<workspace>/extraction_state.json`
- `<workspace>/result.json`
- `<workspace>/topics.log`
- `<workspace>/gemini_rotation_state.json` snapshot debug nếu có.
- Bundle JSON/PDF trong `gemini_pipeline/Output/<pdf_stem>/<pdf_stem>.json`, `Topic/`, `Lesson/`.

Trong review-first backend lớn, service đọc `result.json` và lưu `topics` vào MongoDB. Khi user approve, service ghi `<workspace>/approved_topics.json`.

## 5. Luồng tách Lesson

Entry point review-first:

- File: `gemini_pipeline/scripts/light_extract_job.py`
- Hàm: `_run_lessons(workspace: Path, config: dict)`

Lesson stage hiện tại không gọi Gemini. Nó tổng hợp lesson từ `raw_lessons` đã được Gemini trả về trong Topic stage và cắt theo topic đã duyệt.

Luồng thực tế:

1. Yêu cầu `<workspace>/approved_topics.json` tồn tại. Nếu không có, raise `FileNotFoundError`.
2. Đọc approved topics từ `approved_topics.json`.
3. Yêu cầu `<workspace>/extraction_state.json` tồn tại. Nếu không có, raise `FileNotFoundError("extraction_state.json not found — topics stage must run first")`.
4. Đọc `raw_lessons` từ `extraction_state.json`.
5. Đọc `book_stem` từ state, default `"book"`.
6. Đọc PDF gốc từ `config["source_pdf_path"]`.
7. Nếu có `<workspace>/debug_config.json` và `enabled=true`, có thể chỉ xử lý một topic theo `topic_index`.
8. Với từng topic đã duyệt:
   - Lấy `t_start`, `t_end`.
   - Duyệt `raw_lessons`.
   - Lesson được chọn nếu range lesson giao với range topic: `l_end >= t_start and l_start <= t_end`.
   - Dùng `seen_raw_keys` theo `(l_start, l_end)` để tránh duplicate.
   - Clamp lesson vào topic: `start=max(l_start, t_start)`, `end=min(l_end, t_end)`.
   - Nếu topic không có lesson nào, tạo fallback lesson có range bằng topic và title/heading của topic.
9. Ghi incremental `<workspace>/lessons_partial.json`.
10. Rebuild bundle từ topics đã duyệt và lessons mới:
    - `bundle_dir = workspace / book_stem`
    - `_build_topic_pdfs(bundle_dir, book_stem, pdf_path, approved_topics)`
    - `_build_lesson_pdfs(bundle_dir, book_stem, pdf_path, lessons_out)`
    - `_write_bundle_manifest(bundle_dir, book_stem, approved_topics, lessons_out)`
11. Cập nhật `extraction_state.json` thêm `rebuilt_bundle_path`.
12. Ghi `<workspace>/result.json` gồm `{ "ok": true, "bundle_path": "...", "lessons": [...] }`.
13. Ghi `<workspace>/progress.json` với `status="reviewing_lessons"`.

Output chính của Lesson stage:

- `<workspace>/lessons_partial.json`
- `<workspace>/result.json`
- `<workspace>/lessons.log`
- `<workspace>/<book_stem>/Topic/...` rebuilt theo approved topics.
- `<workspace>/<book_stem>/Lesson/...` rebuilt theo lessons.
- `<workspace>/<book_stem>/<book_stem>.json` manifest rebuilt.

Trong backend lớn, `approve_topics_and_start_lessons` ghi `<workspace>/approved_topics.json` từ topics đang lưu trong MongoDB rồi gọi `light_extract_job.py --stage lessons`.

## 6. Quan hệ Topic -> Lesson

Lesson extraction bắt buộc phụ thuộc Topic stage chạy trước.

Cụ thể:

- Lesson stage yêu cầu `approved_topics.json`.
- Lesson stage yêu cầu `extraction_state.json`.
- `extraction_state.json` phải có `raw_lessons` do Topic stage lấy từ Gemini response ban đầu.
- Lesson stage không tự đọc mục lục bằng Gemini lần nữa.
- Lesson stage dùng topics đã duyệt, không dùng raw topics trực tiếp.
- `approved_topics.json` là list item dạng phẳng:

```json
[
  {
    "name": "topic_01",
    "start": 7,
    "end": 15,
    "heading": "CHỦ ĐỀ 1.",
    "title": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC"
  }
]
```

Quan hệ range:

- `raw_lessons` có `start/end` theo trang PDF thật sau normalize.
- Mỗi approved topic có `start/end`.
- Lesson thuộc topic nếu hai range giao nhau.
- Khi đưa lesson vào topic, range lesson được clamp vào range topic.
- Nếu một topic không chứa raw lesson nào, tạo fallback lesson có cùng range với topic.

Điều `AI-Extract` cần giữ:

- Topic phải được review/approve trước khi lesson stage chạy.
- Lesson stage nên dùng `topics_approved.json`, không dùng trực tiếp `topics_raw.json`.
- Phải giữ `raw_lessons` từ kết quả Topic stage, vì lesson stage hiện dựa vào dữ liệu này.
- Nếu muốn tối giản hơn, `AI-Extract` có thể lưu `raw_lessons.json` riêng thay vì giấu trong `extraction_state.json`.

## 7. Output JSON thực tế

### Topic list phẳng

Quan sát từ `topics_partial.json` và `approved_topics.json`:

```json
[
  {
    "name": "topic_01",
    "start": 7,
    "end": 15,
    "heading": "CHỦ ĐỀ 1.",
    "title": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC"
  }
]
```

### Lesson list phẳng

Quan sát từ `lessons_partial.json` và `approved_lessons.json`:

```json
[
  {
    "name": "lesson_01",
    "start": 7,
    "end": 10,
    "heading": "Bài 1.",
    "title": "LÀM QUEN VỚI TRÍ TUỆ NHÂN TẠO"
  }
]
```

### Manifest bundle

Quan sát từ `<workspace>/<book_stem>/<book_stem>.json` và `Output/<pdf_stem>/<pdf_stem>.json`:

```json
{
  "offset": 0,
  "list_topic": [
    {
      "topic_01": {
        "start": 7,
        "end": 15,
        "heading": "CHỦ ĐỀ 1.",
        "title": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC"
      }
    }
  ],
  "list_lesson": [
    {
      "lesson_01": {
        "start": 7,
        "end": 10,
        "heading": "Bài 1.",
        "title": "LÀM QUEN VỚI TRÍ TUỆ NHÂN TẠO"
      }
    }
  ]
}
```

Lưu ý: `_write_bundle_manifest` hard-code `"offset": 0` khi rebuild từ approved topics/lessons. Manifest sau normalize trong `pdf_output._normalize_from_start_printed` không giữ `offset`; sample bundle trong ReviewWorkspace có `"offset": 0`.

### Topic metadata theo PDF đã cắt

File dạng `<bundle>/Topic/topic_01/<book_stem>_topic_01.json`:

```json
{
  "kind": "topic",
  "name": "topic_01",
  "start": 7,
  "end": 15,
  "source_pdf": "/absolute/source.pdf",
  "pdf": "/absolute/topic.pdf",
  "topic_num": "01",
  "topic_name": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC",
  "raw_heading": "CHỦ ĐỀ 1.",
  "raw_title": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC"
}
```

### Lesson metadata theo PDF đã cắt

File dạng `<bundle>/Lesson/lesson_01/<book_stem>_lesson_01.json`:

```json
{
  "kind": "lesson",
  "name": "lesson_01",
  "start": 7,
  "end": 10,
  "source_pdf": "/absolute/source.pdf",
  "pdf": "/absolute/lesson.pdf",
  "lesson_num": "01",
  "lesson_name": "LÀM QUEN VỚI TRÍ TUỆ NHÂN TẠO",
  "raw_heading": "Bài 1.",
  "raw_title": "LÀM QUEN VỚI TRÍ TUỆ NHÂN TẠO"
}
```

## 8. File cần adapt sang AI-Extract

| Source file in gemini_pipeline | Purpose | Needed for Topic? | Needed for Lesson? | Adapt strategy for AI-Extract |
|---|---|---:|---:|---|
| `sgk_extract/prompts.py` | Prompt TOC Topic/Lesson và prompt verify topic start | Có | Gián tiếp | Copy/adapt chỉ `build_topic_lesson_prompt` và `build_topic_verify_prompt` vào `app/pipeline/gemini_extract/prompts.py`. Không copy prompt chunk. |
| `sgk_extract/gemini_runner.py` | Gọi Gemini qua pool và parse JSON loose | Có | Không trực tiếp | Adapt parse JSON và runner cho PDF. Nên dùng Gemini client hiện có/được chuẩn hóa trong AI-Extract thay vì phụ thuộc backend lớn. |
| `sgk_extract/gemini_client.py` | Upload PDF lên Gemini, generate_content, key rotation wrapper | Có | Không trực tiếp | Không copy nguyên nếu AI-Extract đã có `app/services/gemini/client.py`. Cần port phần `generate_with_pdf` hoặc tạo method tương đương. |
| `sgk_extract/les_top_pipeline.py` | Tạo preview 20 trang, verify offset, standalone `run_extract_save_split` | Có | Gián tiếp | Adapt `_make_preview_first_pages`, `_make_single_page_pdf`, `verify_topics_and_get_offset`. Không cần `run_extract_save_split` nguyên nếu AI-Extract dùng service/job riêng. |
| `sgk_extract/pdf_output.py` | Normalize manifest, flatten, split PDF, write metadata | Có | Có | Adapt tối thiểu `normalize_manifest`, `_flatten_start_printed_items`, `_flatten_list_items`, `split_pdf_by_ranges`; cân nhắc bỏ `prepare_workspace/save_manifest/split_from_manifest` nếu AI-Extract tự quản workspace. |
| `scripts/light_extract_job.py` | Review-first orchestration theo stage topics/lessons/chunks | Có | Có | Không copy nguyên. Dùng làm blueprint để viết `topic_runner.py` và `lesson_runner.py` nhỏ trong AI-Extract. |
| `scripts/connect.py` | Tạo KeyManager từ config/backend GeminiRotationPool | Có | Không trực tiếp | Không nên copy nguyên vì phụ thuộc `FastAPI-Khoa-Luan/app/services/infrastructure/gemini_client.py`. AI-Extract nên dùng config/client riêng. |
| `app/services/mongo/book_review_service.py` | Tạo ReviewWorkspace, gọi subprocess stage, ghi approved topics | Tham khảo | Tham khảo | Không copy. Chỉ tham khảo flow review-first và tên file JSON. AI-Extract đã có file-based job skeleton. |

## 9. File không nên copy sang AI-Extract ở giai đoạn này

Không nên copy các phần sau:

- `sgk_extract/chunk_pipeline.py`: chunk extraction ngoài phạm vi hiện tại.
- `sgk_extract/chunk_postprocess.py`: postprocess chunk/cutline, liên quan Kaggle/OCR và không cần cho Topic/Lesson.
- `scripts/kaggle/*`: Kaggle OCR/cutline/postprocess ngoài phạm vi.
- `scripts/keyword_extract_book.py`, `scripts/keyword_extract_one.py`: keyword extraction ngoài phạm vi.
- `scripts/auto_split.py` nguyên file: chạy full pipeline gồm chunk, Kaggle, keyword.
- `scripts/sync_bundle.py`: dùng sync/rebuild bundle khi review UI chỉnh từng item; AI-Extract có thể làm file JSON trước, chưa cần sync PDF preview phức tạp.
- `scripts/recut_topic_preview.py`: phục vụ preview recut cho UI; ngoài phạm vi API-only giai đoạn đầu.
- `FastAPI-Khoa-Luan/app/services/mongo/*`, `app/routers/mongo/*`: phụ thuộc MongoDB/review UI/backend lớn.
- `FastAPI-Khoa-Luan/app/services/sync/*`, PostgreSQL/Neo4j/MinIO services: heavy-stage import/sync ngoài phạm vi.

Lý do: AI-Extract hiện chỉ cần PDF upload, Topic extraction, review JSON, Lesson extraction từ approved topics, và output JSON file-based.

## 10. Cách thiết kế adapter trong AI-Extract

Mapping đề xuất:

`app/pipeline/gemini_extract/topic_runner.py`

- Nhận `pdf_path`, `job_output_dir`, model/config.
- Tạo preview 20 trang.
- Build prompt Topic/Lesson.
- Gọi Gemini runner.
- Verify offset.
- Normalize manifest.
- Trả về `topics`, `raw_lessons`, manifest/raw payload.
- Không tự xử lý HTTP.

`app/pipeline/gemini_extract/lesson_runner.py`

- Nhận `approved_topics`, `raw_lessons`, `pdf_path`.
- Dùng logic range từ `_run_lessons`.
- Tạo `lessons`.
- Không gọi Gemini nếu giữ đúng flow hiện tại.
- Có thể không cắt PDF ở phiên bản đầu nếu AI-Extract chỉ cần JSON; nếu cần preview PDF sau này, port `_slice_pdf`, `_build_topic_pdfs`, `_build_lesson_pdfs`.

`app/pipeline/gemini_extract/prompts.py`

- Chứa `build_topic_lesson_prompt`.
- Chứa `build_topic_verify_prompt`.
- Không đưa prompt chunk/keyword.

`app/pipeline/gemini_extract/pdf_utils.py`

- Chứa tạo preview PDF, single page PDF, normalize manifest, flatten item, split PDF nếu cần.
- Cần giữ logic offset `start_printed + offset` và `printed_end_of_main - 1`.

`app/services/extraction/topic_service.py`

- Điều phối job-level:
  - Lấy `workspace/uploads/{job_id}/original.pdf`.
  - Gọi `topic_runner`.
  - Ghi `topics_raw.json`, `topics.json`, `raw_lessons.json` hoặc `extraction_state.json`.
  - Cập nhật `job.json` status `reviewing_topics`.

`app/services/extraction/lesson_service.py`

- Yêu cầu `topics_approved.json`.
- Đọc `raw_lessons.json`.
- Gọi `lesson_runner`.
- Ghi `lessons_raw.json`, `lessons.json`.
- Cập nhật `job.json` status `reviewing_lessons`.

`app/services/storage/workspace_service.py`

- Quản lý path theo `job_id`.
- Ghi/đọc JSON.
- Không chứa logic Gemini hoặc logic range.

## 11. API review-first sau này sẽ dùng flow này như thế nào

AI-Extract có thể hỗ trợ review-first không cần UI bằng JSON files và API calls.

1. `POST /api/extract/jobs`
   - Upload PDF.
   - Tạo `job_id`.
   - Lưu `workspace/uploads/{job_id}/original.pdf`.
   - Đã có skeleton trong AI-Extract.

2. `POST /api/extract/jobs/{job_id}/topics/extract`
   - Dùng `original.pdf`.
   - Chạy adapted `topic_runner`.
   - Lưu `topics_raw.json`.
   - Lưu editable `topics.json`.
   - Lưu `raw_lessons.json` hoặc `extraction_state.json`.
   - Set `status = reviewing_topics`.

3. `PUT /api/extract/jobs/{job_id}/topics`
   - Ghi topics đã sửa vào `topics.json`.

4. `POST /api/extract/jobs/{job_id}/topics/approve`
   - Copy hoặc validate `topics.json`.
   - Ghi `topics_approved.json`.

5. `POST /api/extract/jobs/{job_id}/lessons/extract`
   - Require `topics_approved.json`.
   - Require `raw_lessons.json` từ Topic stage.
   - Chạy adapted `lesson_runner`.
   - Lưu `lessons_raw.json`.
   - Lưu editable `lessons.json`.
   - Set `status = reviewing_lessons`.

Điểm quan trọng: Lesson stage của pipeline cũ không phải một Gemini extraction độc lập. Nó là bước tổng hợp từ `raw_lessons` và `approved_topics`.

## 12. Những điểm cần kiểm tra bằng chạy thử

- Chạy `light_extract_job.py --stage topics` trên một PDF nhỏ hoặc một SGK thật.
- Xác nhận `topics_partial.json` luôn có shape phẳng `{name,start,end,heading,title}`.
- Xác nhận `extraction_state.json` luôn có `raw_lessons`.
- Xác nhận manifest normalize đúng với các sách có offset khác 0.
- Xác nhận `printed_end_of_main` hoạt động đúng khi sách không có phụ lục rõ ràng.
- Chạy `light_extract_job.py --stage lessons` sau khi ghi `approved_topics.json`.
- Xác nhận `lessons_partial.json` và `result.json` đúng khi user chỉnh range topic.
- Xác nhận trường hợp topic không có lesson tạo fallback lesson có hợp lý không.
- Xác nhận Gemini key rotation trong AI-Extract có cần port `generate_with_pdf` hay thay bằng client hiện có.
- Xác nhận model nên dùng `gemini-2.5-flash` hay `gemini-2.5-flash-lite` cho AI-Extract.
- Xác nhận có cần cắt PDF Topic/Lesson trong AI-Extract giai đoạn đầu hay chỉ cần JSON.

## 13. Kết luận đề xuất cho bước tiếp theo

Đề xuất thứ tự triển khai trong AI-Extract:

1. Giữ job/storage skeleton hiện có.
2. Implement API review-first cho topics bằng stub trước:
   - extract topics.
   - edit topics.
   - approve topics.
3. Adapt real `topic_runner` từ logic `_run_topics`, nhưng bỏ MongoDB/subprocess/heavy-stage.
4. Lưu `raw_lessons` rõ ràng thành `raw_lessons.json`.
5. Implement lesson extraction từ `topics_approved.json` + `raw_lessons.json`.
6. Chỉ sau khi Topic/Lesson JSON ổn định mới cân nhắc PDF preview/cut bundle nếu cần.

Rủi ro khi adapt:

- `sgk_extract/gemini_client.py` và `scripts/connect.py` phụ thuộc `FastAPI-Khoa-Luan/app/services/infrastructure/gemini_client.py`; không thể copy nguyên mà không kéo theo backend lớn.
- Topic stage gọi Gemini nhiều lần: một lần cho preview mục lục và nhiều lần verify offset từng topic. Cần quản lý rate limit/key rotation.
- Lesson stage phụ thuộc `raw_lessons` sinh ra ở Topic stage; nếu không lưu field này trong AI-Extract thì không thể tái tạo đúng flow cũ.
- Logic normalize dựa mạnh vào mục lục có `Chủ đề <SỐ>.`, `Bài <SỐ>.` và `printed_end_of_main`; sách format khác có thể cần test riêng.
- Pipeline cũ vừa tạo JSON vừa cắt PDF/bundle. AI-Extract nên tách mục tiêu: JSON trước, PDF preview sau nếu thật sự cần.
