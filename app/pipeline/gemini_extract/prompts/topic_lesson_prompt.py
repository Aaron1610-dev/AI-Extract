"""Topic/Lesson structure extraction prompt."""


def build_topic_lesson_prompt() -> str:
    return """
Bạn là hệ thống trích xuất cấu trúc sách giáo khoa từ các trang mục lục hoặc phần đầu sách.

Hãy đọc PDF được cung cấp, ưu tiên phần MỤC LỤC, và trích xuất danh sách Chủ đề và Bài học xuất hiện trong sách.

Yêu cầu bắt buộc:
- Chỉ trả về JSON hợp lệ.
- Không dùng markdown code fence.
- Không giải thích thêm.
- Không tự bịa chủ đề hoặc bài học không xuất hiện trong mục lục.
- Giữ nguyên dấu tiếng Việt, chữ hoa/chữ thường và cách viết tiêu đề nếu có thể.
- Ưu tiên dùng số trang in trên sách.
- Các field trang phải là số nguyên khi có thể.
- Nếu chỉ thấy trang bắt đầu, chỉ cần trả start_printed.
- Không cần tự đoán end_printed nếu mục lục không ghi rõ.

JSON cần đúng shape sau:
{
  "topics": [
    {
      "name": "topic_01",
      "start_printed": 5,
      "heading": "CHỦ ĐỀ 1.",
      "title": "MÁY TÍNH VÀ XÃ HỘI TRI THỨC"
    }
  ],
  "lessons": [
    {
      "name": "lesson_01",
      "start_printed": 5,
      "heading": "Bài 1.",
      "title": "Hệ điều hành"
    }
  ],
  "printed_end_of_main": 100
}

Quy tắc:
- topics phải là mảng.
- lessons phải là mảng.
- name chuẩn hóa lần lượt là topic_01, topic_02, lesson_01, lesson_02, ...
- start_printed là số trang in trong sách.
- heading giữ nhãn như "CHỦ ĐỀ 1." hoặc "Bài 1.".
- title là tên chủ đề/bài học, nên bỏ nhãn heading nếu có thể.
- printed_end_of_main là trang in cuối cùng của phần nội dung chính nếu phát hiện được từ mục lục.
""".strip()
