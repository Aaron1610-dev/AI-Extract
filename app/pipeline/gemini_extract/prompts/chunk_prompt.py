"""Prompt builder for debug chunk extraction from one lesson PDF."""

from __future__ import annotations


def build_chunk_prompt_start_head(
    total_pages: int,
    lesson_title: str | None = None,
) -> str:
    lesson_label = lesson_title or "bài học được cung cấp"

    return f"""
Bạn là hệ thống trích xuất chunk từ một PDF bài học sách giáo khoa.

PDF được cung cấp chỉ chứa một bài học: {lesson_label}.
PDF bài học này có {total_pages} trang.

Nhiệm vụ: trích xuất các chunk theo heading cấp cao nhất trong bài học.

Chỉ lấy các heading cấp cao. Heading cấp cao có thể là số Ả Rập hoặc số La Mã như:
- "1."
- "2."
- "3."
- "I."
- "II."
- "III."
- "IV."
- "V."

Phải giữ nguyên kiểu heading đúng như in trên PDF:
- Nếu PDF dùng "I." thì heading phải là "I.", không đổi thành "1.".
- Nếu PDF dùng "II." thì heading phải là "II.", không đổi thành "2.".
- Nếu PDF dùng "1." thì heading phải là "1.", không đổi thành "I.".
- Nếu bài này dùng heading La Mã, dùng La Mã nhất quán.
- Nếu bài này dùng heading số Ả Rập, dùng số Ả Rập nhất quán.
- Không trộn hai kiểu trừ khi PDF nhìn thấy rõ là có trộn.

Không lấy:
- a), b), c)
- bullet
- câu hỏi
- hoạt động
- ví dụ
- luyện tập
- nhiệm vụ
- các bước nhỏ
- heading tự bịa không xuất hiện trong PDF

Yêu cầu JSON:
- Chỉ trả về JSON hợp lệ.
- Không dùng markdown.
- Không dùng code fence.
- Không giải thích thêm.
- Không có trailing comma.
- Không có summary.
- Không có lesson_name.
- Không có lesson_title.
- Không có topic_name.
- Không có topic_title.
- Không có pdf_path.
- Không có start_page_in_lesson.
- Không có end_page_in_lesson.
- Chỉ dùng field start.
- start là số trang 1-based bên trong PDF bài học.
- Nếu không có heading cấp cao hợp lệ, trả về {{"chunks": []}}.

Quy tắc chunk:
- chunk_01 phải có first_chunk: true.
- chunk_01 không được có content_head.
- chunk_02 trở đi phải có content_head: true hoặc false.
- chunk_02 trở đi không được có first_chunk.
- heading chỉ chứa nhãn heading cấp cao, ví dụ "1." hoặc "I.", không chứa title.
- title chỉ chứa phần chữ sau heading, giữ nguyên cách viết trên PDF.
- Không tự tạo heading hoặc title nếu không thấy rõ trên trang.
- Chuỗi heading phải nhất quán với kiểu in trên PDF:
  - nếu là số Ả Rập thì theo thứ tự "1.", "2.", "3.";
  - nếu là số La Mã thì theo thứ tự "I.", "II.", "III.";
  - không đổi số La Mã sang số Ả Rập hoặc ngược lại.

Quy tắc xác định content_head:
- content_head=true nghĩa là trên cùng trang start, phía TRÊN heading vẫn còn nội dung thật của chunk trước.
- Nội dung thật có thể là:
  - đoạn văn
  - hình ảnh
  - sơ đồ
  - bảng
  - hộp thông tin
  - ví dụ
  - câu hỏi
  - bài tập
  - phần tổng kết
  - bất kỳ nội dung học tập nào thuộc mục trước
- Không chỉ xét chữ. Nếu phía trên heading có hình ảnh, hộp thông tin, sơ đồ hoặc bảng thì vẫn tính là có nội dung thật.
- Không tính header, footer, số trang, tên bài, tên chương, đường trang trí hoặc khoảng trắng.
- content_head=false chỉ khi heading bắt đầu sạch ở đầu vùng nội dung, phía trên không có nội dung học tập thật.

Ví dụ content_head=true:
Trên cùng trang start có:
[đoạn văn/hình ảnh/hộp thông tin của mục trước]
"3. MỐI QUAN HỆ GIỮA TĂNG TRƯỞNG KINH TẾ VÀ PHÁT TRIỂN BỀN VỮNG"
=> content_head=true

Ví dụ content_head=false:
Trên cùng trang start có:
[header/tên bài/số trang]
"3. MỐI QUAN HỆ GIỮA TĂNG TRƯỞNG KINH TẾ VÀ PHÁT TRIỂN BỀN VỮNG"
=> content_head=false

JSON cần đúng shape sau:
{{
  "chunks": [
    {{
      "name": "chunk_01",
      "start": 1,
      "first_chunk": true,
      "heading": "I.",
      "title": "ĐỐI TƯỢNG NGHIÊN CỨU CỦA VẬT LÍ VÀ MỤC TIÊU CỦA MÔN VẬT LÍ"
    }},
    {{
      "name": "chunk_02",
      "start": 4,
      "content_head": true,
      "heading": "II.",
      "title": "TẬP HỢP"
    }}
  ]
}}
""".strip()


def build_chunk_prompt(
    lesson_name: str,
    lesson_title: str | None = None,
    total_pages: int | None = None,
) -> str:
    del lesson_name
    return build_chunk_prompt_start_head(
        total_pages=total_pages or 1,
        lesson_title=lesson_title,
    )
