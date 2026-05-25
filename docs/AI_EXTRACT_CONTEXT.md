# AI-Extract - Context dự án

## 1. Tổng quan dự án

AI-Extract là một dịch vụ FastAPI nhẹ dùng cho bài toán trích xuất thông tin từ file PDF sách giáo khoa.

Mục tiêu của repository này là tách riêng phần extraction cần thiết khỏi backend luận văn lớn hơn. AI-Extract chỉ tập trung cung cấp API đơn giản để nhận PDF, chạy logic trích xuất, trả JSON và lưu kết quả ra thư mục workspace/outputs.

Tại thời điểm tạo tài liệu này, repository hiện có:

- `README.md`: đang trống.
- `requirements.txt`: khai báo FastAPI, Uvicorn, Pydantic, python-dotenv và các dependency nền tảng.
- `app/main.py`: entry FastAPI hiện tại, đang include các router health, debug và keywords.
- `run.py`: chạy Uvicorn với `app.main:app`.
- `app/api/routes/`: có `health.py`, `debug.py`, `keywords.py`.
- `app/services/gemini/`: có service hiện tại cho Gemini keyword và hạ tầng Gemini client.
- `app/services/extraction/`, `app/services/storage/`, `app/pipeline/gemini_extract/`: đã được tạo sẵn cho extraction sau này, hiện chỉ là placeholder.
- `app/schemas/`: có schema keyword, schema extraction job và placeholder schema common.
- `app/utils/`: có utility JSON/text hiện dùng bởi keyword service và placeholder filename utility.
- `app/core/config.py`: đọc cấu hình từ `app/core/config.env`.
- `app/core/paths.py`: khai báo base path cho app/workspace.
- `app/core/config.env`: có cấu hình ứng dụng và Gemini. Không nên hard-code hoặc lan truyền secret trong tài liệu/code mới.

Các phần extraction Topic/Lesson từ PDF chưa được triển khai trong repository này.

## 2. Quan hệ với FastAPI-Khoa-Luan / gemini_pipeline

Có một workspace/repository khác tên là `FastAPI-Khoa-Luan`. Repository đó là hệ thống luận văn lớn hơn và có thư mục `gemini_pipeline`.

Trong hệ thống lớn, `gemini_pipeline` được dùng để xử lý PDF sách giáo khoa, trích xuất topic/lesson/chunk, tạo artifact trên disk, tạo review workspace, và sau đó backend chính import/sync dữ liệu vào MongoDB, PostgreSQL, Neo4j và MinIO.

Đối với AI-Extract, chỉ reuse hoặc adapt phần tối thiểu cần thiết cho:

- Trích xuất Topic từ PDF.
- Trích xuất Lesson từ PDF và/hoặc từ kết quả Topic đã trích xuất.
- Trả kết quả JSON qua API.
- Lưu kết quả JSON xuống workspace/outputs.

AI-Extract không chịu trách nhiệm database sync, import nặng, review workspace, hoặc các stage phụ trợ của backend luận văn đầy đủ.

## 3. Phạm vi đơn giản hiện tại

Phạm vi hiện tại của AI-Extract:

- Upload file PDF sách giáo khoa.
- Trích xuất Topic.
- Trích xuất Lesson.
- Trả JSON response từ API.
- Lưu JSON output ra disk.
- Chỉ cung cấp API FastAPI, không có UI.

Các endpoint extraction thực tế chưa được triển khai tại thời điểm tạo tài liệu này.

## 4. Ngoài phạm vi hiện tại

Các chức năng sau chưa thuộc phạm vi AI-Extract ở giai đoạn này:

- Chunk extraction.
- Review UI hoặc màn hình duyệt/chỉnh sửa kết quả.
- Kaggle OCR/cutline.
- Keyword extraction cho pipeline PDF mới, trừ khi sau này có yêu cầu tích hợp rõ ràng.
- MongoDB.
- PostgreSQL.
- Neo4j.
- MinIO.
- Import/sync heavy-stage từ artifact vào database/object storage.
- Authentication/authorization, trừ khi được bổ sung ở giai đoạn sau.

## 5. Output file dự kiến

Kết quả extraction dự kiến được lưu dưới dạng JSON trong workspace/outputs.

Tên file dự kiến:

- `topics.json`: chứa danh sách topic đã trích xuất.
- `lessons.json`: chứa danh sách lesson đã trích xuất.

Quy ước thư mục dự kiến:

- `workspace/outputs/`

Tên file, cấu trúc thư mục con, và format JSON chính xác cần theo implementation thực tế ở bước triển khai sau. Nếu có nhiều job hoặc nhiều PDF cùng lúc, cần quyết định thêm cách đặt `job_id`, folder theo job, hoặc tên file theo tài liệu.

## 6. Hành vi API dự kiến

Các endpoint job đã được implement ở mức skeleton. Các endpoint Topic/Lesson bên dưới vẫn là định hướng dự kiến, chưa khẳng định đã được triển khai.

### `POST /api/extract/jobs`

Trạng thái: đã implement skeleton file-based ở Step 1.

Mục tiêu:

- Nhận PDF upload qua `multipart/form-data`, field `file`.
- Validate filename có đuôi `.pdf`.
- Tạo `job_id` bằng UUID.
- Tạo workspace theo job.
- Lưu PDF gốc và metadata job.
- Trả metadata job.

File được tạo:

- `workspace/uploads/{job_id}/original.pdf`
- `workspace/outputs/{job_id}/job.json`

Status ban đầu:

- `uploaded`

### `GET /api/extract/jobs/{job_id}`

Trạng thái: đã implement skeleton file-based ở Step 1.

Mục tiêu:

- Đọc `workspace/outputs/{job_id}/job.json`.
- Trả metadata job.
- Nếu không tìm thấy job, trả `404`.

### `POST /api/extract/topics`

Mục tiêu:

- Nhận một file PDF.
- Chạy topic extraction.
- Trả JSON chứa danh sách topic.
- Lưu kết quả ra file JSON, dự kiến là `topics.json` trong workspace/outputs hoặc thư mục job tương ứng.

Request dự kiến:

- `multipart/form-data`.
- Field file PDF: Cần kiểm tra trong bước triển khai.

Response dự kiến:

- JSON chứa danh sách topics.
- Có thể kèm metadata như tên file, output path, model, thời gian xử lý hoặc `job_id` nếu cần.

### `POST /api/extract/lessons`

Mục tiêu:

- Nhận một file PDF và/hoặc sử dụng `topics.json` đã trích xuất trước đó.
- Chạy lesson extraction.
- Trả JSON chứa danh sách lessons.
- Lưu kết quả ra file JSON, dự kiến là `lessons.json` trong workspace/outputs hoặc thư mục job tương ứng.

Request dự kiến:

- Có thể là `multipart/form-data` với PDF.
- Có thể nhận thêm `topics.json`, `job_id`, hoặc đường dẫn output từ bước topic extraction.
- Cách truyền dữ liệu chính xác: Chưa xác định.

Response dự kiến:

- JSON chứa danh sách lessons.
- Có thể kèm metadata như tên file, topic source, output path, model, thời gian xử lý hoặc `job_id` nếu cần.

### Topic review endpoints theo job

Trạng thái: đã implement bằng stub data ở Step 2. Chưa gọi Gemini.

Endpoint đã có:

- `POST /api/extract/jobs/{job_id}/topics/extract`
- `GET /api/extract/jobs/{job_id}/topics`
- `PUT /api/extract/jobs/{job_id}/topics`
- `POST /api/extract/jobs/{job_id}/topics/approve`

File được tạo hoặc cập nhật:

- `workspace/outputs/{job_id}/topic/topic_raw.json`
- `workspace/outputs/{job_id}/topic/topics.json`
- `workspace/outputs/{job_id}/topic/topics_approved.json`
- `workspace/outputs/{job_id}/lesson/lesson_raw.json`

`lesson/lesson_raw.json` được lưu ngay ở Topic stage vì pipeline cũ trong `FastAPI-Khoa-Luan/gemini_pipeline` trả về cả topics và lessons ở Topic stage. Lesson stage sau này cần `topic/topics_approved.json` cộng với `lesson/lesson_raw.json`.

## 7. Quy tắc phát triển

- Giữ implementation đơn giản, API-only.
- Không copy toàn bộ heavy-stage pipeline từ `gemini_pipeline`.
- Không đưa database dependency vào AI-Extract ở giai đoạn này.
- Không thêm UI.
- Giữ cấu trúc project hiện có khi có thể.
- Ưu tiên các file nhỏ, rõ trách nhiệm:
  - router cho endpoint.
  - service cho logic extraction.
  - schema/model cho request/response.
  - config cho đường dẫn workspace/outputs và model/API settings.
- Khi adapt code từ `gemini_pipeline`, chỉ mang sang các file tối thiểu cần cho Topic và Lesson extraction.
- Không refactor các phần keyword/Gemini hiện có nếu không cần cho extraction API.
- Không hard-code secret. Cấu hình nhạy cảm phải đi qua env/config phù hợp.

## 8. Change Log / Context Updates

### 2026-05-25

- Tạo file context ban đầu cho hướng phát triển đơn giản: PDF -> Topic/Lesson JSON API.
- Ghi nhận AI-Extract là service FastAPI nhẹ, tách khỏi backend luận văn đầy đủ.
- Xác định phạm vi hiện tại chỉ gồm upload PDF, trích xuất Topic/Lesson, trả JSON và lưu output JSON.
- Ghi rõ các phần ngoài phạm vi: chunk extraction, review UI, Kaggle OCR/cutline, keyword extraction pipeline mới, database/object storage và heavy import/sync.
- Bổ sung kế hoạch kiến trúc code sạch cho Topic/Lesson extraction.
- Quyết định dùng workspace folder theo `job_id` để tránh ghi đè output khi xử lý nhiều sách.
- Định hướng tạo layer riêng `app/pipeline/gemini_extract/` để chứa code tối thiểu adapt từ `gemini_pipeline`, tránh trộn logic pipeline với FastAPI service.
- Refactor cấu trúc source code thành các layer rõ hơn: route, schema, service, storage, pipeline và utils.
- Giữ nguyên các API hiện có: health, debug và keyword.
- Tạo sẵn các folder tương lai cho review-first extraction.
- Tạo folder nền `workspace/uploads` và `workspace/outputs`.
- Chưa implement logic Topic/Lesson extraction.
- Implement skeleton extraction job file-based.
- Thêm API tạo job upload PDF: `POST /api/extract/jobs`.
- Thêm API đọc metadata job: `GET /api/extract/jobs/{job_id}`.
- Tạo `job.json` trong `workspace/outputs/{job_id}` khi upload PDF.
- Chuẩn hóa tên storage helper là `workspace_service.py`.
- Chưa implement Topic/Lesson extraction và chưa gọi Gemini trong extraction workflow.
- Implement Topic review API bằng stub data.
- Thêm quy ước file topic review ban đầu, hiện đã refactor vào `topic/` và `lesson/`.
- Chưa implement Gemini Topic extraction thật.
- Chưa implement Lesson extraction.
- Implement Lesson review API dùng approved topics và raw lessons.
- Thêm quy ước file lesson review ban đầu, hiện đã refactor vào `lesson/`.
- Chưa implement Gemini Lesson extraction thật.
- Chưa copy `gemini_pipeline`.
- Refactor review output files vào subfolder `topic/` và `lesson/`.
- Đổi raw output của Topic stage thành `topic/topic_raw.json`.
- Chuyển raw lesson source sang `lesson/lesson_raw.json`.
- Đổi field trong Topic raw payload từ `raw_lessons` thành `lessons`.
- Bỏ quy ước `lessons_raw.json` riêng; `lesson/lesson_raw.json` là nguồn raw lesson từ Topic stage.
- Giữ nguyên public API behavior.
- Bổ sung kế hoạch inspect AI-Extract Gemini client trước khi adapt real Topic extraction.
- Thêm hàm Gemini PDF-capable `generate_with_pdf(...)` cho Topic extraction sau này.
- Giữ nguyên behavior text-only Gemini hiện dùng bởi keyword APIs.
- Topic stub vẫn đang active; chưa implement real Topic extraction.
- Thêm minimal Topic/Lesson prompt cho Gemini PDF extraction sau này.
- Thêm parser/normalizer cho Gemini JSON response.
- Thêm PDF page utilities và range split helpers.
- Thêm dependency `pypdf`.
- Chuẩn hóa future split PDF folders là `topic/doc/` và `lesson/doc/`.
- Preview PDF creation cố ý defer cho module/người triển khai khác.
- Topic stub vẫn đang active; real Topic extraction chưa wire vào API.
- Thêm manually callable real `topic_runner.py` cho test thủ công.
- Runner có thể gọi Gemini PDF extraction và normalize topics/lessons.
- Runner chưa wire vào Topic API; Topic stub vẫn đang active.
- Adapt automatic offset detection từ `FastAPI-Khoa-Luan/gemini_pipeline`.
- Thêm `make_single_page_pdf(...)` để tạo PDF 1 trang phục vụ verify offset.
- Thêm `offset_detector.py` dùng single-page verification PDFs và `generate_with_pdf(...)`.
- Auto offset detection hiện chỉ dùng trong manual `topic_runner.py`; Topic API vẫn dùng stub.

Các phiên Codex sau cần cập nhật section này khi kiến trúc, phạm vi, endpoint, cấu trúc output hoặc dependency chính thay đổi.

## 9. Câu hỏi mở / bước triển khai tiếp theo

- Kiểm tra trong `FastAPI-Khoa-Luan/gemini_pipeline` để xác định file nào cần copy/adapt cho Topic extraction.
- Kiểm tra trong `FastAPI-Khoa-Luan/gemini_pipeline` để xác định file nào cần copy/adapt cho Lesson extraction.
- Hoàn thiện cấu trúc chi tiết bên trong `workspace/uploads/{job_id}` và `workspace/outputs/{job_id}` khi triển khai.
- Quyết định có dùng `job_id` hay không.
- Quyết định lesson extraction nhận input là:
  - PDF gốc cộng với `topics.json`.
  - `job_id` tham chiếu output đã có.
  - Hoặc một cơ chế khác.
- Thiết kế schema JSON tối thiểu cho Topic.
- Thiết kế schema JSON tối thiểu cho Lesson.
- Implement FastAPI endpoint `POST /api/extract/topics`.
- Implement FastAPI endpoint `POST /api/extract/lessons`.
- Thêm hướng dẫn test thủ công cơ bản bằng `curl` hoặc Swagger UI.

## 10. Kiến trúc code đề xuất cho Topic/Lesson extraction

Kiến trúc đề xuất nên giữ rõ ranh giới giữa FastAPI route, service orchestration, file storage và code pipeline adapt từ `FastAPI-Khoa-Luan/gemini_pipeline`.

### Cấu trúc file đề xuất

`app/api/routes/extract.py`

- Chứa các FastAPI endpoint extraction.
- Endpoint dự kiến:
  - `POST /api/extract/topics`
  - `POST /api/extract/lessons`
- Chỉ nên xử lý HTTP layer: nhận request, validate input cơ bản, gọi service, trả response hoặc map lỗi sang HTTP error.
- Không đặt logic đọc PDF, prompt Gemini, hoặc xử lý pipeline trực tiếp trong router.

`app/schemas/extraction.py`

- Chứa request/response schema cho extraction API.
- Model dự kiến:
  - `TopicItem`
  - `LessonItem`
  - `TopicExtractionResponse`
  - `LessonExtractionResponse`
- Field chi tiết của `TopicItem` và `LessonItem`: Cần kiểm tra trong bước triển khai theo output thực tế từ `gemini_pipeline`.
- Response nên có tối thiểu `job_id`, danh sách kết quả, và đường dẫn output JSON nếu phù hợp.

`app/services/storage/workspace_service.py`

- Chịu trách nhiệm tạo workspace folder theo `job_id`.
- Lưu PDF upload vào đúng vị trí.
- Ghi JSON output ra disk.
- Đọc lại `topic/topics.json` hoặc `topic/topics_approved.json` khi lesson extraction cần dùng topic đã có.
- Không chứa logic trích xuất bằng Gemini.

`app/services/extraction/topic_service.py`

- Chịu trách nhiệm orchestration cho Topic API.
- Flow chính: nhận PDF upload/path, gọi file storage để lưu file, gọi `topic_runner`, lưu `topic/topics.json`, trả dữ liệu về router.
- Không chứa code pipeline chi tiết nếu code đó có thể đặt trong `app/pipeline/gemini_extract/`.

`app/services/extraction/lesson_service.py`

- Chịu trách nhiệm orchestration cho Lesson API.
- Flow chính: xác định input lesson extraction, lấy PDF/topics source, gọi `lesson_runner`, lưu `lesson/lessons.json`, trả dữ liệu về router.
- Cần hỗ trợ thiết kế cuối cùng: nhận `job_id`, nhận PDF mới, hoặc nhận PDF kèm topics source.

`app/pipeline/gemini_extract/`

- Layer riêng cho code tối thiểu adapt từ `FastAPI-Khoa-Luan/gemini_pipeline`.
- Không copy toàn bộ pipeline lớn.
- File đề xuất:
  - `topic_runner.py`: chạy phần trích xuất topic.
  - `lesson_runner.py`: chạy phần trích xuất lesson.
  - `pdf_utils.py`: utility PDF tối thiểu cần cho Topic/Lesson.
  - `prompts.py`: prompt tối thiểu cho Topic/Lesson.
- Layer này không nên import FastAPI router. Nếu cần config, nhận qua tham số hoặc đọc từ config service đơn giản.

### Workspace theo `job_id`

Nên dùng `job_id` để tránh ghi đè file khi xử lý nhiều sách hoặc nhiều request cùng lúc.

Cấu trúc dự kiến:

```text
workspace/
  uploads/
    {job_id}/
      original.pdf
  outputs/
    {job_id}/
      job.json
      topic/
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

Quy ước:

- `workspace/uploads/{job_id}/original.pdf`: file PDF gốc đã upload.
- `workspace/outputs/{job_id}/topic/topics.json`: editable topic review output.
- `workspace/outputs/{job_id}/lesson/lessons.json`: editable lesson review output.
- `workspace/outputs/{job_id}/topic/doc/`: future folder cho PDF topic được cắt.
- `workspace/outputs/{job_id}/lesson/doc/`: future folder cho PDF lesson được cắt.
- Cách sinh `job_id`: Cần kiểm tra trong bước triển khai, nhưng nên dùng giá trị unique như UUID.
- Nếu API nhận `job_id`, service phải kiểm tra folder/file tương ứng có tồn tại trước khi chạy bước tiếp theo.

### Flow dự kiến

Topic API:

1. Client gọi `POST /api/extract/topics` với PDF.
2. Router validate file upload ở mức cơ bản.
3. `topic_extraction_service` tạo hoặc nhận `job_id`.
4. `workspace_service` lưu PDF vào `workspace/uploads/{job_id}/original.pdf`.
5. Service gọi `app/pipeline/gemini_extract/topic_runner.py`.
6. Service lưu kết quả vào `workspace/outputs/{job_id}/topic/topics.json`.
7. API trả JSON chứa `job_id` và mảng topics.

Lesson API:

1. Client gọi `POST /api/extract/lessons`.
2. API nhận `job_id` hoặc PDF + nguồn topics, tùy thiết kế cuối cùng.
3. `lesson_extraction_service` xác định PDF và topics source.
4. Service gọi `app/pipeline/gemini_extract/lesson_runner.py`.
5. Service lưu kết quả vào `workspace/outputs/{job_id}/lesson/lessons.json`.
6. API trả JSON chứa `job_id` và mảng lessons.

### Nguyên tắc tách lớp

- Router chỉ biết HTTP request/response.
- Service điều phối workflow, không chứa chi tiết pipeline nặng.
- File storage xử lý đường dẫn, folder, upload và JSON disk I/O.
- Pipeline layer chứa logic adapt tối thiểu từ `gemini_pipeline`.
- Không thêm database, UI, chunk extraction, Kaggle OCR/cutline, MinIO, MongoDB, PostgreSQL hoặc Neo4j.
- Không refactor keyword APIs hiện có nếu không cần cho Topic/Lesson extraction.

## 11. Cấu trúc source code sau khi refactor

Source code đã được refactor để chuẩn bị cho hướng review-first PDF Topic/Lesson extraction, nhưng chưa implement logic extraction.

### Route layer

`app/api/routes/` là HTTP route layer.

Hiện có:

- `app/api/routes/health.py`: giữ endpoint health hiện có.
- `app/api/routes/debug.py`: giữ endpoint debug Gemini key hiện có.
- `app/api/routes/keywords.py`: giữ các endpoint keyword hiện có.
- `app/api/routes/extract_jobs.py`: chứa skeleton endpoint tạo/đọc extraction job.
- `app/api/routes/extract_topics.py`: chứa Topic review endpoints dùng stub data.
- `app/api/routes/extract_lessons.py`: chứa Lesson review endpoints dùng range-overlap từ approved topics và raw lessons.

`app/main.py` import router từ `app.api.routes.*`. Public endpoint hiện có không đổi.

### Schema layer

`app/schemas/` chứa Pydantic schema.

Hiện có:

- `app/schemas/keyword.py`: schema cho keyword API hiện có, được move từ schema cũ.
- `app/schemas/common.py`: placeholder cho shared response schema nếu cần sau này.
- `app/schemas/extraction.py`: có `ExtractionJobStatus`, `ExtractionJobResponse`, Topic schemas/responses và Lesson schemas/responses.

### Gemini service layer

`app/services/gemini/` chứa Gemini client và logic liên quan keyword.

Hiện có:

- `app/services/gemini/client.py`: Gemini rotation client hiện có.
- `app/services/gemini/keyword_service.py`: keyword extraction service hiện có.

Layer này tiếp tục phục vụ keyword APIs. Không thêm logic Topic/Lesson vào đây nếu logic đó thuộc pipeline PDF extraction.

### Extraction service layer

`app/services/extraction/` được tạo sẵn cho orchestration review-first extraction sau này.

File placeholder hiện có:

- `job_service.py`: quản lý skeleton job extraction file-based, gồm tạo job từ PDF upload, đọc job metadata và update status.
- `review_service.py`: dự kiến quản lý review-first workflow.
- `topic_service.py`: điều phối Topic review API bằng stub data; chưa gọi Gemini.
- `lesson_service.py`: điều phối Lesson review API bằng range-overlap từ `topic/topics_approved.json` và `lesson/lesson_raw.json`; chưa gọi Gemini.

`review_service.py` hiện chỉ là placeholder, chưa có business logic.

### Storage service layer

`app/services/storage/` được tạo sẵn cho file/workspace JSON I/O.

Hiện có:

- `workspace_service.py`: helper file-based cho tạo workspace, lưu PDF upload, ghi/đọc JSON và resolve path theo `job_id`.

### Pipeline adapter layer

`app/pipeline/gemini_extract/` được tạo sẵn để chứa code tối thiểu adapt từ `FastAPI-Khoa-Luan/gemini_pipeline`.

File placeholder hiện có:

- `topic_runner.py`
- `lesson_runner.py`
- `prompts.py`
- `pdf_utils.py`

Layer này giúp tránh trộn code pipeline adapt từ `gemini_pipeline` với FastAPI route/service layer.

### Utils layer

`app/utils/` chứa utility dùng chung.

Hiện có:

- `json_utils.py`: chứa helper parse JSON và normalize text đang được keyword service dùng.
- `filename_utils.py`: placeholder cho helper tên file/path sau này.

### Workspace folders

Folder nền đã được tạo:

```text
workspace/
  uploads/
    .gitkeep
  outputs/
    .gitkeep
```

`workspace/uploads` và `workspace/outputs` là base storage folder cho PDF upload và JSON output. File sinh ra trong hai folder này được ignore qua `.gitignore`, còn `.gitkeep` được giữ lại để preserve folder.

Bước refactor này chỉ sắp xếp lại source structure. Topic extraction và Lesson extraction chưa được implement, chưa copy `gemini_pipeline`, chưa thêm database, UI, chunk extraction, Kaggle, MinIO, MongoDB, PostgreSQL hoặc Neo4j.

## 12. Step 1 - Job/workspace storage skeleton đã implement

Step 1 thêm foundation tối thiểu cho review-first PDF extraction workflow.

Endpoint đã có:

- `POST /api/extract/jobs`
- `GET /api/extract/jobs/{job_id}`

Khi tạo job, hệ thống:

1. Nhận PDF upload từ field `file`.
2. Kiểm tra filename có đuôi `.pdf`.
3. Sinh `job_id` bằng UUID.
4. Tạo folder:
   - `workspace/uploads/{job_id}/`
   - `workspace/outputs/{job_id}/`
5. Lưu PDF thành:
   - `workspace/uploads/{job_id}/original.pdf`
6. Ghi metadata job vào:
   - `workspace/outputs/{job_id}/job.json`
7. Trả metadata gồm `job_id`, `status`, `source_file`, `upload_path`, `output_dir`, `created_at`, `updated_at`.

Status hiện có trong schema:

- `uploaded`
- `extracting_topics`
- `reviewing_topics`
- `topics_approved`
- `extracting_lessons`
- `reviewing_lessons`
- `lessons_approved`
- `error`

Step này chỉ tạo skeleton job/storage. Topic extraction, Lesson extraction, review processing và Gemini calls chưa được implement.

`app/services/storage/workspace_service.py` là module chịu trách nhiệm quản lý workspace theo `job_id`, gồm:

- Tạo base folder `workspace/uploads` và `workspace/outputs`.
- Tạo folder theo job.
- Lưu PDF gốc thành `original.pdf`.
- Ghi/đọc JSON.
- Resolve path cho upload dir, output dir, original PDF và `job.json`.
- Resolve path cho `topic/topic_raw.json`, `topic/topics.json`, `topic/topics_approved.json`.
- Resolve path cho `lesson/lesson_raw.json`, `lesson/lessons.json`, `lesson/lessons_approved.json`.
- Kiểm tra job tồn tại bằng `job_exists(job_id)`.

Change Log bổ sung:

- Implemented file-based extraction job skeleton.
- Added PDF upload job creation.
- Added GET job metadata endpoint.
- Standardized storage helper name as `workspace_service.py`.
- No Topic/Lesson extraction implemented yet.

## 13. Step 2 - Topic review API bằng stub data đã implement

Step 2 thêm luồng review-first cho Topic ở mức backend file-based. Đây là stub, chưa gọi Gemini và chưa dùng `gemini_pipeline`.

Endpoint đã có:

- `POST /api/extract/jobs/{job_id}/topics/extract`
- `GET /api/extract/jobs/{job_id}/topics`
- `PUT /api/extract/jobs/{job_id}/topics`
- `POST /api/extract/jobs/{job_id}/topics/approve`

Luồng hiện tại:

1. `POST /api/extract/jobs/{job_id}/topics/extract`
   - Kiểm tra `job.json`.
   - Kiểm tra `workspace/uploads/{job_id}/original.pdf`.
   - Set status `extracting_topics`.
   - Ghi full raw output vào `topic/topic_raw.json`.
   - Ghi bản topic review được phép sửa vào `topic/topics.json`.
   - Ghi raw lesson source vào `lesson/lesson_raw.json`.
   - Set status `reviewing_topics`.

2. `GET /api/extract/jobs/{job_id}/topics`
   - Đọc `topic/topics.json`.
   - Nếu chưa có topics, trả `404` với message `Topics have not been extracted for this job yet.`

3. `PUT /api/extract/jobs/{job_id}/topics`
   - Nhận body `{ "topics": [...] }`.
   - Ghi đè `topic/topics.json`.
   - Không sửa `topic/topic_raw.json`.
   - Không sửa `topic/topics_approved.json`.
   - Nếu job chưa ở `topics_approved`, giữ/set status `reviewing_topics`.

4. `POST /api/extract/jobs/{job_id}/topics/approve`
   - Đọc `topic/topics.json`.
   - Ghi `topic/topics_approved.json`.
   - Set status `topics_approved`.

Stub topics hiện tại:

```json
[
  {
    "name": "topic_01",
    "start": 1,
    "end": 5,
    "heading": "CHỦ ĐỀ 1.",
    "title": "CHỦ ĐỀ MẪU"
  }
]
```

Stub raw lessons hiện tại:

```json
[
  {
    "name": "lesson_01",
    "start": 1,
    "end": 3,
    "heading": "Bài 1.",
    "title": "BÀI HỌC MẪU 1"
  },
  {
    "name": "lesson_02",
    "start": 4,
    "end": 5,
    "heading": "Bài 2.",
    "title": "BÀI HỌC MẪU 2"
  }
]
```

Các file output theo job:

- `workspace/outputs/{job_id}/topic/topic_raw.json`
- `workspace/outputs/{job_id}/topic/topics.json`
- `workspace/outputs/{job_id}/topic/topics_approved.json`
- `workspace/outputs/{job_id}/lesson/lesson_raw.json`

`topic/topic_raw.json` có shape:

```json
{
  "job_id": "...",
  "source": "stub",
  "topics": [],
  "lessons": []
}
```

`topic/topics.json` và `topic/topics_approved.json` chỉ chứa mảng topic. `lesson/lesson_raw.json` chỉ chứa mảng raw lesson lấy từ Topic stage.

Lesson extraction phải yêu cầu `topic/topics_approved.json` và `lesson/lesson_raw.json`.

## 14. Step 3 - Lesson review API bằng range-overlap đã implement

Step 3 thêm luồng review-first cho Lesson ở mức backend file-based. Đây chưa phải Gemini Lesson extraction thật. Logic hiện tại mô phỏng pipeline cũ: dùng `topic/topics_approved.json` cộng với `lesson/lesson_raw.json` sinh ra ở Topic stage.

Endpoint đã có:

- `POST /api/extract/jobs/{job_id}/lessons/extract`
- `GET /api/extract/jobs/{job_id}/lessons`
- `PUT /api/extract/jobs/{job_id}/lessons`
- `POST /api/extract/jobs/{job_id}/lessons/approve`

Luồng hiện tại:

1. `POST /api/extract/jobs/{job_id}/lessons/extract`
   - Kiểm tra `job.json`.
   - Kiểm tra `workspace/uploads/{job_id}/original.pdf`.
   - Yêu cầu `topic/topics_approved.json`; nếu thiếu trả `409` với message `Topics must be approved before extracting lessons.`
   - Yêu cầu `lesson/lesson_raw.json`; nếu thiếu trả `409` với message `Raw lessons are missing. Run topic extraction first.`
   - Set status `extracting_lessons`.
   - Đọc approved topics và raw lessons.
   - Gán raw lessons vào topic bằng range-overlap.
   - Ghi bản review được phép sửa vào `lesson/lessons.json`.
   - Set status `reviewing_lessons`.

2. `GET /api/extract/jobs/{job_id}/lessons`
   - Đọc `lesson/lessons.json`.
   - Nếu chưa có lessons, trả `404` với message `Lessons have not been extracted for this job yet.`

3. `PUT /api/extract/jobs/{job_id}/lessons`
   - Nhận body `{ "lessons": [...] }`.
   - Nếu job đã `lessons_approved`, trả `409` với message `Lessons are already approved. Re-open lesson review is not implemented yet.`
   - Ghi đè `lesson/lessons.json`.
   - Không sửa `lesson/lesson_raw.json`.
   - Không sửa `lesson/lessons_approved.json`.
   - Set/giữ status `reviewing_lessons`.

4. `POST /api/extract/jobs/{job_id}/lessons/approve`
   - Đọc `lesson/lessons.json`.
   - Ghi `lesson/lessons_approved.json`.
   - Set status `lessons_approved`.

Range rule hiện dùng:

- Raw lesson thuộc approved topic nếu `lesson.end >= topic.start` và `lesson.start <= topic.end`.
- Khi thêm lesson vào topic:
  - `start = max(lesson.start, topic.start)`
  - `end = min(lesson.end, topic.end)`
- Nếu topic không có raw lesson giao range, tạo fallback lesson:
  - `name = "lesson_fallback_for_{topic.name}"`
  - `start = topic.start`
  - `end = topic.end`
  - `heading = topic.heading`
  - `title = topic.title`

Các file output theo job:

- `workspace/outputs/{job_id}/lesson/lesson_raw.json`
- `workspace/outputs/{job_id}/lesson/lessons.json`
- `workspace/outputs/{job_id}/lesson/lessons_approved.json`

`lesson/lesson_raw.json` là raw lesson source từ Topic stage. `lesson/lessons.json` là generated/reviewable lesson list và mỗi item có `topic_name`, `topic_title`. `lesson/lessons_approved.json` là final approved lesson list.

Lý do không gọi Gemini ở Step 3: trong `FastAPI-Khoa-Luan/gemini_pipeline`, Lesson stage không gọi Gemini độc lập. Lesson stage dùng raw lessons đã có từ Topic stage và approved topics đã được review để tạo lesson output cuối.
