# OLD_CHUNK_KAGGLE_CONTEXT.md

## 1. Tổng quan mục tiêu cũ

Flow chunk/Kaggle/PaddleOCR trong `FastAPI-Khoa-Luan/gemini_pipeline` giải quyết bài toán sau:

- Gemini tách lesson PDF thành các chunk theo heading cấp cao như `1.`, `2.`, `3.`.
- Mỗi chunk ban đầu được cắt theo page range nguyên trang, nên khi một chunk mới bắt đầu giữa trang, PDF của chunk trước và chunk hiện tại có thể bị dư/thiếu phần nội dung.
- Kaggle chạy PaddleOCR để tìm vị trí heading thật trên ảnh trang đầu của chunk.
- Từ bbox/dòng OCR chứa heading, code tính `cutline` theo trục y.
- Nếu `content_head=true`, trang đầu của chunk hiện tại được cắt thành:
  - phần trên trả về cuối chunk trước;
  - phần dưới giữ lại làm đầu chunk hiện tại.
- Nếu chunk đầu hoặc heading số `1.` cần xử lý đặc biệt, code có thể dùng `bot-only` để thay page 0 của chính chunk.
- Kernel tạo debug image/JSON và cập nhật trực tiếp chunk PDFs trong bundle, sau đó zip bundle đã postprocess để backend tải về và apply vào `Output/<book_stem>`.

Mục tiêu cốt lõi không phải OCR toàn bộ sách, mà là xác định đường cắt chính xác quanh heading chunk để sửa PDF chunk khi heading bắt đầu giữa trang.

## 2. Danh sách file đã kiểm tra

### `../FastAPI-Khoa-Luan/gemini_pipeline/sgk_extract/chunk_pipeline.py`

- Purpose: chạy Gemini trên từng lesson PDF để tạo chunk candidates, tính start/end, cắt chunk PDF ban đầu.
- Important functions:
  - `run_extract_and_split_chunks_for_book(...)`
  - `_flatten_start_head(...)`
  - `_compute_chunks_from_start_head(...)`
  - `_is_junk_candidate(...)`
  - `_heading_valid_in_page(...)`
  - `_to_ranges(...)`
- Inputs:
  - `Output/<book_stem>/Lesson/**/*.pdf`
  - Gemini key manager.
  - Prompt `build_chunk_prompt_start_head(total_pages)`.
- Outputs:
  - `Output/<book_stem>/Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.pdf`
  - JSON meta cạnh PDF chunk.
  - `.keywords.json` placeholder.
- Reuse potential:
  - Rất liên quan cho AI-Extract: logic prompt shape, filter heading/title rác, end calculation và split từ lesson PDF.
  - Không nên copy nguyên vì AI-Extract đang có workspace khác và debug endpoint riêng.

### `../FastAPI-Khoa-Luan/gemini_pipeline/sgk_extract/chunk_postprocess.py`

- Purpose: PaddleOCR postprocess để tìm cutline và cập nhật chunk PDFs.
- Important functions:
  - `build_ocr()`
  - `process_one_chunk(...)`
  - `render_pdf_page0_to_bgr(...)`
  - `run_ocr_any(...)`
  - `iter_dets_paddleocr(...)`
  - `iter_dets_predict(...)`
  - `group_to_lines(...)`
  - `extract_heading_num(...)`
  - `build_expected_letters_from_title(...)`
  - `robust_match_count(...)`
  - `draw_debug(...)`
  - `split_and_save(...)`
  - `split_and_save_bot_only(...)`
  - `replace_page_with_png_inplace(...)`
  - `update_pdfs_for_content_head(...)`
  - `update_pdf_page0_with_bot_only(...)`
  - `run_postprocess_for_book(...)`
- Inputs:
  - Chunk meta JSON trong `Output/<book_stem>/Chunk/...`.
  - Chunk PDF cạnh JSON.
  - PaddleOCR model/runtime.
- Outputs:
  - `DebugCutlines/*_cutline.png`
  - `DebugCutlines/*_cutline.json`
  - `DebugCutlines/*_cutline_top.png`
  - `DebugCutlines/*_cutline_bot.png`
  - PDF chunk đã được sửa inplace.
  - JSON meta được mark `extract` hoặc `extract_heading`.
- Reuse potential:
  - Rất liên quan cho bước AI-Extract sau: OCR cutline local hoặc Kaggle worker.
  - Nên port theo module nhỏ, không mang toàn bộ config/global flags nếu chưa cần.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/kaggle/cli.py`

- Purpose: local CLI orchestration để build dataset, push Kaggle dataset, push kernel, download output zip, verify request/status và apply zip vào `Output/`.
- Important functions:
  - `main()`
  - `_inject_embedded_run_request(...)`
  - `setup_logging(...)`
- Inputs:
  - `book_stem`
  - flags `--run-local`, `--skip-dataset`, `--skip-kernel`, `--no-apply`, `--overwrite`.
- Outputs:
  - `kaggle_pack/`
  - `scripts/kaggle/kernels/debug-cutlines-auto/run_request.json`
  - downloaded zip in `Output/_kaggle_outputs/debug-cutlines-auto/downloads/`
  - extracted/applied `Output/<book_stem>`.
- Reuse potential:
  - Hữu ích nếu AI-Extract cần Kaggle remote worker.
  - Nên thiết kế lại theo job workspace của AI-Extract thay vì dùng global `Output/<book_stem>`.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/kaggle/utils.py`

- Purpose: helper cho Kaggle CLI.
- Important functions:
  - `ensure_kaggle_cli()`
  - `build_kaggle_pack(...)`
  - `push_dataset_version(...)`
  - `wait_for_dataset_marker_ready(...)`
  - `push_kernel(...)`
  - `download_kernel_output(...)`
  - `safe_extract_zip_to_output(...)`
  - `clean_dl_dir(...)`
- Inputs:
  - `Output/<book_stem>`
  - `sgk_extract/chunk_postprocess.py`
  - Kaggle dataset/kernel refs.
- Outputs:
  - `kaggle_pack/sgk_extract/chunk_postprocess.py`
  - `kaggle_pack/Output/<book_stem>`
  - `book_stem.txt`
  - `dataset-metadata.json`
  - extracted output from kernel zip.
- Reuse potential:
  - Dataset marker/request-id logic rất đáng học lại.
  - Copy nguyên không phù hợp vì phụ thuộc `gemini_pipeline/Output`.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/kaggle/config.py`

- Purpose: khai báo Kaggle refs và local path.
- Important values:
  - `KERNEL_REF = dat261303/debug-cutlines-auto`
  - `DATASET_ID = dat261303/kaggle-pack`
  - `KERNEL_DIR`
  - `PACK_DIR`
  - `KAGGLE_OUT_ROOT`
  - `DL_DIR`
  - `OUTPUT_ROOT`
- Reuse potential:
  - Chỉ nên dùng làm tham khảo env/config names.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/kaggle/kernels/debug-cutlines-auto/script.py`

- Purpose: Kaggle kernel script chạy trong môi trường Kaggle, install dependencies, resolve dataset, load `chunk_postprocess.py`, chạy PaddleOCR postprocess, zip output.
- Important sections:
  - embedded `_EMBEDDED_RUN_REQUEST_JSON`
  - đọc `run_request.json`
  - ghi `current_run_status.json` và `current_run_status_{request_id}.json`
  - install PyMuPDF, pypdfium2, paddlepaddle, paddleocr
  - resolve dataset root `/kaggle/input/datasets/dat261303/kaggle-pack`
  - validate `book_stem.txt`
  - detect stale dataset mismatch
  - iterate chunk JSONs
  - call `cp.process_one_chunk(...)`
  - zip `Output/<book_stem>`
- Inputs:
  - Kaggle dataset `dat261303/kaggle-pack`
  - `Output/<book_stem>`
  - `sgk_extract/chunk_postprocess.py`
  - `book_stem.txt`
  - embedded/fallback `run_request.json`.
- Outputs:
  - `current_run_status.json`
  - `current_run_status_{request_id}.json`
  - `<book_stem>_{request_id}_postprocessed.zip`
  - modified chunk PDFs and debug files inside zip.
- Reuse potential:
  - Rất liên quan nếu AI-Extract dùng Kaggle remote compute.
  - Nên tách thành kernel package riêng cho AI-Extract nếu cần.

### `../FastAPI-Khoa-Luan/app/services/mongo/book_review_service.py`

- Purpose: backend heavy-stage orchestration trong hệ thống cũ.
- Relevant section:
  - heavy stage copy bundle vào `gemini_pipeline/Output/<book_stem>`.
  - chạy subprocess `[python, -m, scripts.kaggle.cli, book_stem, --overwrite]`.
  - parse `[STAGE:...]` markers để update DB progress.
  - sau Kaggle, update `bundle_path` sang `Output/<book_stem>`.
  - tiếp tục keyword extraction và import/sync heavy stage.
- Reuse potential:
  - Không copy vào AI-Extract vì phụ thuộc MongoDB và heavy import.
  - Hữu ích để biết progress markers và subprocess behavior.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/auto_split.py`

- Purpose: standalone full pipeline: Topic/Lesson -> Chunk -> Kaggle -> Keyword.
- Important functions:
  - `run_kaggle_cli(...)`
  - `main()`
- Reuse potential:
  - Chỉ tham khảo thứ tự stage. Không copy nguyên vào AI-Extract.

### `../FastAPI-Khoa-Luan/gemini_pipeline/scripts/debug_chunk_split.py`

- Purpose: script debug cũ để chạy chunk split và push dataset.
- Reuse potential:
  - Tham khảo lịch sử, không nên reuse trực tiếp.

### `../FastAPI-Khoa-Luan/gemini_pipeline/sgk_extract/prompts.py`

- Purpose: prompt cũ cho Topic/Lesson/Chunk.
- Relevant functions:
  - `build_chunk_prompt_start_head(total_pages)`
  - `build_content_head_verify_prompt(...)`
- Reuse potential:
  - AI-Extract đã có prompt chunk riêng theo minimal JSON. Chỉ dùng file cũ để hiểu rule `content_head`.

### `../FastAPI-Khoa-Luan/gemini_pipeline/sgk_extract/pdf_output.py`

- Purpose: split PDF theo ranges, tạo Topic/Lesson bundle.
- Relevant function:
  - `split_pdf_by_ranges(...)`
- Reuse potential:
  - AI-Extract đã có `split_pdf_range(...)`; chỉ cần giữ nguyên nguyên tắc 1-based inclusive.

## 3. Luồng xử lý cũ end-to-end

### 3.1 Tạo Topic/Lesson bundle

Flow đầy đủ cũ bắt đầu bằng `scripts/auto_split.py`:

1. `run_extract_save_split(...)` trong `les_top_pipeline` tạo `Output/<book_stem>/Topic` và `Output/<book_stem>/Lesson`.
2. Mỗi lesson có folder/PDF/JSON trong `Output/<book_stem>/Lesson`.
3. Sau đó `run_extract_and_split_chunks_for_book(...)` xử lý từng lesson PDF.

### 3.2 Chunk split local bằng Gemini

File: `sgk_extract/chunk_pipeline.py`

1. Đọc `Output/<book_stem>/Lesson/**/*.pdf`.
2. Với mỗi lesson PDF:
   - đếm `total_pages`;
   - build prompt `build_chunk_prompt_start_head(total_pages)`;
   - gọi Gemini qua `extract_structure_from_pdf(...)`;
   - đọc `raw["list_chunk"]`.
3. `_flatten_start_head(...)` chuyển output dạng:

```json
[
  {
    "chunk_01": {
      "start": 1,
      "content_head": false,
      "heading": "1.",
      "title": "..."
    }
  }
]
```

thành tuple `(start, content_head, heading, title)`.

4. Filter:
   - `_is_junk_candidate(...)` reject heading không phải numeric `^\d+\.$`, title thuộc nhóm bài tập/luyện tập/hoạt động/ví dụ...
   - `_heading_valid_in_page(...)` dùng text extract từ page để tránh nhầm sub-item như `a)`, `b)`.
5. `_compute_chunks_from_start_head(...)` tính end:
   - nếu chunk kế tiếp `content_head=True`, chunk hiện tại end = next.start;
   - nếu `content_head=False`, end = next.start - 1;
   - chunk cuối end = total_pages;
   - nếu không có items, tạo fallback `chunk_01` title `KHÔNG CÓ MỤC CHÍNH`.
6. `split_pdf_by_ranges(...)` cắt PDF lesson thành chunk PDFs.
7. Ghi JSON meta cạnh mỗi chunk PDF, gồm:
   - `source_lesson_pdf`
   - `lesson_stem`
   - `chunk`
   - `chunk_pdf`
   - `heading`
   - `title`
   - `start`
   - `end`
   - `content_head`
   - `total_pages`
   - `chunk_count`
8. Ghi `.keywords.json` placeholder nếu chưa có.

### 3.3 Build Kaggle dataset pack

File: `scripts/kaggle/utils.py`, function `build_kaggle_pack(...)`.

Local pack:

```text
kaggle_pack/
  book_stem.txt
  dataset-metadata.json
  sgk_extract/
    chunk_postprocess.py
  Output/
    <book_stem>/
      Topic/
      Lesson/
      Chunk/
```

`book_stem.txt` là marker để kernel biết chính xác sách cần xử lý.

### 3.4 Push dataset và chờ propagation

File: `scripts/kaggle/cli.py`.

1. Gọi `kaggle datasets version -p kaggle_pack ... --dir-mode zip`.
2. `wait_for_dataset_marker_ready(...)` tải `book_stem.txt` từ remote dataset để kiểm tra remote marker đã match `book_stem`.
3. Nếu marker chưa match, poll tiếp trong timeout. Đây là fix cho lỗi stale Kaggle dataset.

### 3.5 Tạo run_request.json và push kernel

Mỗi kernel attempt tạo:

```json
{
  "expected_book_stem": "...",
  "request_id": "8_hex_chars",
  "requested_at": "ISO datetime",
  "attempt": 1
}
```

`cli.py` làm hai việc:

- inject payload vào `_EMBEDDED_RUN_REQUEST_JSON` trong `script.py`;
- ghi fallback `scripts/kaggle/kernels/debug-cutlines-auto/run_request.json`.

Expected artifacts theo request:

```text
<book_stem>_<request_id>_postprocessed.zip
current_run_status_<request_id>.json
current_run_status.json
```

Sau đó push kernel bằng `kaggle kernels push -p <kernel_dir>`.

### 3.6 Kernel chạy PaddleOCR postprocess

File: `scripts/kaggle/kernels/debug-cutlines-auto/script.py`.

1. Load request từ embedded JSON hoặc `run_request.json`.
2. Ghi status `started`.
3. Install dependencies:
   - PyMuPDF
   - pypdfium2
   - paddlepaddle
   - paddleocr
   - pyclipper, shapely, imgaug, pillow, tqdm, lmdb, attrdict, fire, rapidfuzz, visualdl
4. Resolve dataset root dưới `/kaggle/input/datasets`.
5. Copy/unzip dataset vào `/kaggle/working/kaggle_pack`.
6. Resolve `book_stem` từ `book_stem.txt`, env, hoặc auto-detect single dir.
7. So sánh `book_stem` với `expected_book_stem`. Nếu mismatch:
   - ghi status `failed`, `failure_reason="stale_dataset_mismatch"`;
   - raise error để local CLI retry.
8. Import `chunk_postprocess.py` từ dataset pack.
9. Tìm chunk JSONs dưới `WORK/Output/<book_stem>/Chunk`.
10. Build PaddleOCR bằng `cp.build_ocr()`.
11. Với từng chunk JSON:
    - skip `.keywords.json`, `DebugCutlines`, `*_cutline.json`;
    - chỉ xử lý nếu `content_head=True` hoặc heading num thuộc `FORCE_HEADING_NUMS`;
    - gọi `cp.process_one_chunk(...)`;
    - nếu thành công, mark JSON bằng `extract` hoặc `extract_heading`.
12. Zip `WORK/Output/<book_stem>` thành `<book_stem>_<request_id>_postprocessed.zip`.
13. Ghi status `completed` với summary `ok/skip/fail`.

### 3.7 Local CLI download và apply output

`cli.py` sau khi kernel complete:

1. `clean_dl_dir(...)` xóa stale artifacts.
2. `download_kernel_output(...)` gọi `kaggle kernels output`.
3. Ưu tiên `current_run_status_<request_id>.json`.
4. Xác nhận `request_id` trong status khớp attempt hiện tại.
5. Nếu thiếu zip và status báo `stale_dataset_mismatch` hoặc stale artifact, retry kernel attempt.
6. Verify zip top-level folder đúng `book_stem`.
7. `safe_extract_zip_to_output(...)` extract zip vào `Output/<book_stem>`.

### 3.8 Backend heavy-stage cũ

`app/services/mongo/book_review_service.py`:

1. Copy bundle đã review vào `gemini_pipeline/Output/<book_stem>`.
2. Chạy subprocess:

```bash
python -m scripts.kaggle.cli <book_stem> --overwrite
```

3. Đọc stdout realtime, parse markers:
   - `[STAGE:dataset_building]`
   - `[STAGE:dataset_versioning]`
   - `[STAGE:dataset_versioned]`
   - `[STAGE:kernel_pushing]`
   - `[STAGE:kernel_waiting]`
   - `[STAGE:kernel_done]`
   - `[STAGE:downloading]`
   - `[STAGE:dl_file]`
   - `[STAGE:dl_done]`
   - `[STAGE:extracting]`
   - `[STAGE:applying]`
   - `[STAGE:apply_done]`
4. Update Mongo job progress.
5. Sau Kaggle, set `bundle_path = Output/<book_stem>`.
6. Chạy keyword extraction và heavy import/sync. Phần này ngoài scope AI-Extract.

## 4. Kaggle/PaddleOCR kernel details

### Input kernel mong đợi

Kernel mong dataset có:

```text
/kaggle/input/datasets/dat261303/kaggle-pack/
  book_stem.txt
  sgk_extract/chunk_postprocess.py
  Output/<book_stem>/Chunk/...
```

Có thể ở folder-mode hoặc zip-mode, kernel tự copy/unzip vào:

```text
/kaggle/working/kaggle_pack/
```

### Output kernel ghi

Trong `/kaggle/working`:

```text
current_run_status.json
current_run_status_{request_id}.json
<book_stem>_{request_id}_postprocessed.zip
```

Trong zip:

```text
<book_stem>/Chunk/<lesson_stem>/chunk_XX/
  <lesson_stem>_chunk_XX.pdf
  <lesson_stem>_chunk_XX.json
  DebugCutlines/
    <stem>_cutline.png
    <stem>_cutline.json
    <stem>_cutline_top.png
    <stem>_cutline_bot.png
```

### PaddleOCR initialization

`chunk_postprocess.build_ocr()`:

- `lang="vi"`
- disable orientation/unwarping.
- nếu `DET_NO_RESIZE=True`, dùng `text_det_limit_type="max"` / `det_limit_side_len=4096` hoặc fallback tên tham số cũ.

### Page/image processing

`process_one_chunk(...)`:

1. Đọc JSON meta.
2. Lấy `heading`, `title`, `content_head`.
3. `extract_heading_num(heading)` lấy số heading.
4. Skip nếu không có heading num.
5. Chỉ xử lý nếu:
   - `content_head=True`, hoặc
   - heading num thuộc `FORCE_HEADING_NUMS` hiện là `{1}`.
6. Render page 0 của chunk PDF thành BGR image ở `DPI=260` bằng:
   - ưu tiên `pypdfium2`;
   - fallback PyMuPDF.
7. Chạy OCR:
   - ưu tiên `ocr.ocr(img, cls=False)`;
   - fallback `ocr.predict(...)`.
8. Parse OCR boxes thành list:

```json
{
  "x0": 0.0,
  "y0": 0.0,
  "x1": 100.0,
  "y1": 20.0,
  "text": "...",
  "score": 0.95
}
```

9. Group boxes thành lines bằng y tolerance dựa trên median text box height.

### Heading/title matching

Logic match dùng nhiều mode:

- `prefix_line`: line bắt đầu bằng heading num như `1.` và phần sau là title.
- `heading_left_title`: OCR tách heading `1.` riêng bên trái title.
- `same_line`: heading và title nằm trong cùng group line.
- `merge_next`: heading ở line hiện tại, title nằm ở line kế.

Title match dựa trên initials:

- `build_expected_letters_from_title(title)` lấy chữ cái đầu của các từ in hoa, bỏ dấu.
- `extract_initials_no_case_change(...)` lấy initials từ OCR line.
- `robust_match_count(...)` dùng prefix/skip extra letters/LCS fallback.

Nếu match yếu:

- có thể hard-fail và ghi debug cutline JSON với `failed=true`;
- hoặc `weak_cut` nếu đạt các ngưỡng `WEAK_*`;
- hoặc `force_cut` nếu mode nằm trong `FORCE_CUT_ON_MODES`.

### Cutline y coordinate

Khi tìm được line tốt nhất:

```text
y_line = line.y0 - OFFSET
```

`OFFSET` hiện là `10`.

Debug:

- `draw_debug(...)` vẽ đường đỏ cutline và bbox xanh của line match.
- Ghi `*_cutline.png`.
- Ghi `*_cutline.json` gồm heading, title, expected initials, observed initials, bbox, y_line, image size, split info, pdf update info.

### Cập nhật PDF

Nếu `content_head=True`:

- `split_and_save(...)` tạo `top_png` và `bot_png`.
- `update_pdfs_for_content_head(...)`:
  - thay page 0 của chunk hiện tại bằng `bot_png`;
  - tìm chunk trước và thay last page của chunk trước bằng `top_png`.

Nếu `content_head=False` nhưng heading num nằm trong `FORCE_HEADING_NUMS`:

- `split_and_save_bot_only(...)` chỉ lấy phần dưới heading.
- `update_pdf_page0_with_bot_only(...)` thay page 0 của chính chunk bằng bot image.

PDF update dùng PyMuPDF:

- `replace_page_with_png_inplace(...)`
- tạo PDF tạm;
- thay page bằng image;
- có thể crop page theo image.

## 5. Input/output schema

### 5.1 Gemini chunk raw output cũ

```json
{
  "list_chunk": [
    {
      "chunk_01": {
        "start": 1,
        "content_head": false,
        "heading": "1.",
        "title": "MỆNH ĐỀ"
      }
    },
    {
      "chunk_02": {
        "start": 3,
        "content_head": true,
        "heading": "2.",
        "title": "TẬP HỢP"
      }
    }
  ]
}
```

### 5.2 Chunk meta JSON cũ

```json
{
  "source_lesson_pdf": "/path/to/lesson.pdf",
  "lesson_stem": "lesson_01",
  "chunk": "chunk_02",
  "chunk_pdf": "/path/to/chunk_02.pdf",
  "heading": "2.",
  "title": "TẬP HỢP",
  "start": 3,
  "end": 5,
  "content_head": true,
  "total_pages": 8,
  "chunk_count": 3
}
```

Sau PaddleOCR success có thể thêm:

```json
{
  "extract": true
}
```

hoặc:

```json
{
  "extract_heading": true
}
```

### 5.3 run_request.json

```json
{
  "expected_book_stem": "SGK-TIN-10_0aeec99d",
  "request_id": "d0048cdc",
  "requested_at": "2026-05-18T02:31:13.904000+00:00",
  "attempt": 1
}
```

### 5.4 current_run_status.json

Success:

```json
{
  "request_id": "d0048cdc",
  "expected_book_stem": "SGK-TIN-10_0aeec99d",
  "status": "completed",
  "resolved_book_stem": "SGK-TIN-10_0aeec99d",
  "final_zip": "/kaggle/working/SGK-TIN-10_0aeec99d_d0048cdc_postprocessed.zip",
  "final_zip_name": "SGK-TIN-10_0aeec99d_d0048cdc_postprocessed.zip",
  "summary": {
    "ok": 10,
    "skip": 20,
    "fail": 0
  }
}
```

Stale dataset:

```json
{
  "request_id": "d0048cdc",
  "expected_book_stem": "SGK-TIN-10_0aeec99d",
  "status": "failed",
  "failure_reason": "stale_dataset_mismatch",
  "resolved_book_stem": "SGK-THUD-11_4686d9ff"
}
```

### 5.5 Cutline debug JSON

```json
{
  "chunk_json": "/path/to/chunk.json",
  "chunk_pdf": "/path/to/chunk.pdf",
  "heading": "2.",
  "heading_num": 2,
  "title": "TẬP HỢP",
  "expected_letters": ["T", "H"],
  "matched_prefix": 2,
  "observed_initials": ["T", "H"],
  "line_bbox": {
    "x0": 100.0,
    "y0": 200.0,
    "x1": 500.0,
    "y1": 230.0
  },
  "y_line": 190,
  "dpi": 260,
  "offset_px": 10,
  "image_size": {
    "w": 1800,
    "h": 2400
  },
  "split_info": {
    "y_split": 190,
    "top_saved": true,
    "bot_saved": true,
    "top_h": 190,
    "bot_h": 2210
  },
  "pdf_update": {
    "prev_pdf_updated": true,
    "cur_pdf_updated": true
  },
  "mode": "content_head",
  "best_mode": "prefix_line",
  "failed": false
}
```

## 6. Quan hệ với AI-Extract hiện tại

AI-Extract hiện đã có debug endpoint:

```text
POST /api/extract/jobs/{job_id}/chunks/debug/lesson/{lesson_name}
```

Nó tạo cấu trúc:

```text
workspace/outputs/{job_id}/chunk/{lesson_name}/
  chunk_01.json
  chunk_02.json
  doc/
    chunk_01.pdf
    chunk_02.pdf
```

Khác với old pipeline:

- AI-Extract không dùng `Output/<book_stem>`.
- AI-Extract không dùng nested `Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.pdf`.
- AI-Extract chunk JSON đang tối giản, không chứa lesson/topic metadata.
- AI-Extract chưa có batch chunk extraction.
- AI-Extract chưa có Kaggle/PaddleOCR postprocess.

Điểm nên reuse:

- Rule `content_head` và end calculation.
- PaddleOCR line grouping và heading/title matching.
- Cutline debug artifact.
- PDF update strategy cho `content_head=true`:
  - top về chunk trước;
  - bot về chunk hiện tại.
- Request/status guard nếu dùng Kaggle remote.

Điểm không nên reuse nguyên:

- MongoDB heavy-stage orchestration.
- Keyword extraction stage.
- Import/sync database/object storage.
- Global `Output/<book_stem>` path.
- Dataset/kernel refs hard-coded nếu AI-Extract cần multi-env.

## 7. Đề xuất adapt cho AI-Extract sau này

### 7.1 Bước nhỏ nhất tiếp theo

Trước khi dùng Kaggle, có thể port local postprocess cho đúng một lesson/chunk debug:

1. Dùng output hiện có:
   - `workspace/outputs/{job_id}/chunk/{lesson_name}/chunk_XX.json`
   - `workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_XX.pdf`
2. Render page 0 của chunk PDF.
3. Chạy PaddleOCR local nếu môi trường hỗ trợ.
4. Ghi debug:
   - `workspace/outputs/{job_id}/chunk/{lesson_name}/debug/chunk_XX_cutline.png`
   - `workspace/outputs/{job_id}/chunk/{lesson_name}/debug/chunk_XX_cutline.json`
5. Chưa update PDF inplace cho đến khi chắc cutline đúng.

### 7.2 Nếu cần Kaggle remote

Thiết kế pack theo job:

```text
kaggle_pack/
  run_request.json
  job_id.txt
  workspace/
    outputs/{job_id}/chunk/{lesson_name}/...
  pipeline/
    chunk_postprocess.py
```

Request nên có:

```json
{
  "request_id": "...",
  "job_id": "...",
  "lesson_name": "lesson_01",
  "expected_job_id": "...",
  "requested_at": "...",
  "attempt": 1
}
```

Kernel nên ghi:

```text
current_run_status_{request_id}.json
{job_id}_{lesson_name}_{request_id}_chunk_postprocessed.zip
```

Không nên dùng `book_stem` làm guard chính trong AI-Extract; nên dùng `job_id` và `lesson_name`.

### 7.3 Mapping path cũ -> AI-Extract

| Old pipeline | AI-Extract đề xuất |
|---|---|
| `Output/<book_stem>/Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.pdf` | `workspace/outputs/{job_id}/chunk/{lesson_name}/doc/chunk_XX.pdf` |
| `Output/<book_stem>/Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.json` | `workspace/outputs/{job_id}/chunk/{lesson_name}/chunk_XX.json` |
| `DebugCutlines/` cạnh từng chunk folder | `workspace/outputs/{job_id}/chunk/{lesson_name}/debug/` hoặc `chunk_XX/DebugCutlines/` nếu cần tách per chunk |
| `book_stem.txt` | `job_id.txt` hoặc `run_request.json` |
| `<book_stem>_{request_id}_postprocessed.zip` | `{job_id}_{lesson_name}_{request_id}_chunk_postprocessed.zip` |

## 8. Rủi ro và điểm cần kiểm tra

- PaddleOCR dependency nặng; local macOS/dev environment có thể khó ổn định hơn Kaggle.
- Kernel cũ install dependency runtime, tốn thời gian và dễ fail nếu package version đổi.
- `chunk_postprocess.py` dùng nhiều global flags; khi port nên gom config vào dataclass hoặc function args.
- Logic `update_pdfs_for_content_head(...)` giả định cấu trúc folder cũ để tìm previous chunk. AI-Extract cần rewrite phần tìm previous chunk theo `chunk/{lesson_name}/doc/chunk_XX.pdf`.
- Old code có fallback tạo chunk `KHÔNG CÓ MỤC CHÍNH`; AI-Extract hiện có thể chọn trả `chunks=[]` nếu không có heading cấp cao.
- Stale Kaggle dataset là vấn đề thật trong pipeline cũ; nếu dùng Kaggle trong AI-Extract phải giữ cơ chế request/status guard.
- Cutline dựa vào OCR initials/title uppercase; sách format khác hoặc heading không in hoa có thể giảm độ chính xác.

## 9. Kết luận

Old flow gồm hai phần tách biệt:

1. Gemini local tạo chunk JSON/PDF nguyên trang từ lesson PDFs.
2. Kaggle/PaddleOCR postprocess sửa cutline cho các chunk có heading nằm giữa trang.

AI-Extract hiện mới có debug Gemini chunk extraction cho một lesson. Nếu muốn reuse old Kaggle/PaddleOCR, nên port theo từng bước:

1. Port OCR/cutline debug local cho một chunk hoặc một lesson.
2. Chỉ ghi debug artifact, chưa update PDF.
3. Sau khi cutline đúng, thêm PDF update từ lesson/chunk PDFs.
4. Cuối cùng mới cân nhắc Kaggle remote worker và batch chunk extraction.

Không nên copy toàn bộ old heavy-stage vì nó kéo theo `Output/<book_stem>`, Mongo progress, keyword extraction và import/sync ngoài phạm vi AI-Extract.
