"""Prompts for future Gemini PDF Topic/Lesson extraction."""


def build_topic_lesson_prompt() -> str:
    return """
Bạn là hệ thống trích xuất cấu trúc sách giáo khoa từ PDF.

Hãy đọc toàn bộ file PDF sách giáo khoa được cung cấp và trích xuất cấu trúc chính của sách thành Chủ đề và Bài học.

Yêu cầu bắt buộc:
- Chỉ trả về JSON hợp lệ.
- Không dùng markdown code fence.
- Không giải thích thêm.
- Không tự bịa chủ đề hoặc bài học không xuất hiện trong sách.
- Giữ nguyên dấu tiếng Việt, chữ hoa/chữ thường và cách viết tiêu đề nếu có thể.
- Ưu tiên dùng số trang in trên sách nếu nhìn thấy.
- Nếu không biết end_printed, tạm dùng cùng giá trị với start_printed.
- Nếu actual PDF page index hiển thị hoặc có thể suy ra chắc chắn, có thể thêm field start/end dạng số nguyên.
- Các field trang phải là số nguyên khi có thể.

JSON cần đúng shape sau:
{
  "topics": [
    {
      "name": "topic_01",
      "start_printed": 1,
      "end_printed": 5,
      "heading": "CHỦ ĐỀ 1.",
      "title": "CHỦ ĐỀ MẪU"
    }
  ],
  "lessons": [
    {
      "name": "lesson_01",
      "start_printed": 1,
      "end_printed": 3,
      "heading": "Bài 1.",
      "title": "BÀI HỌC MẪU 1"
    }
  ],
  "printed_end_of_main": 100
}

Quy tắc field:
- topics phải là mảng.
- lessons phải là mảng.
- name phải chuẩn hóa lần lượt là topic_01, topic_02, lesson_01, lesson_02, ...
- start_printed và end_printed là số trang in trên sách.
- heading giữ nhãn như "CHỦ ĐỀ 1." hoặc "Bài 1.".
- title là tên chủ đề/bài học, nên bỏ nhãn heading nếu có thể.
- printed_end_of_main là trang in cuối cùng của phần nội dung chính nếu phát hiện được.
""".strip()


def build_topic_verify_prompt(topic_label: str) -> str:
    return f"""
Bạn được cung cấp một trang PDF đơn lẻ từ sách giáo khoa.

Hãy xác định trang này có phải là trang bắt đầu của chủ đề "{topic_label}" hay không.

Chỉ trả về JSON hợp lệ, không dùng markdown code fence và không giải thích ngoài JSON.

JSON cần đúng shape:
{{
  "is_start": true,
  "confidence": 0.95,
  "reason": "..."
}}
""".strip()
