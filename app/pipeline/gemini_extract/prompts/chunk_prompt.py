"""Prompt builder for debug chunk extraction from one lesson PDF."""

from __future__ import annotations


def build_chunk_prompt(
    lesson_name: str,
    lesson_title: str | None = None,
) -> str:
    lesson_label = lesson_title or lesson_name

    return f"""
Bạn là hệ thống trích xuất chunk từ một bài học trong sách giáo khoa.

PDF được cung cấp chỉ chứa một bài học: {lesson_label}.

Hãy đọc PDF bài học này và trích xuất các chunk/section có ý nghĩa bên trong bài.

Một chunk thường tương ứng với:
- một mục hoặc tiểu mục có đánh số;
- một heading lớn;
- một nhóm hoạt động học tập;
- phần luyện tập, vận dụng hoặc thực hành;
- phần tóm tắt, hộp kiến thức quan trọng nếu có giá trị riêng.

Yêu cầu:
- Chỉ trả về JSON hợp lệ.
- Không dùng markdown code fence.
- Không giải thích thêm.
- Không tự bịa nội dung không có trong bài.
- Không chia quá nhỏ.
- Không tạo một chunk cho từng đoạn văn.
- Dùng số trang tương đối trong PDF bài học.
- start_page_in_lesson và end_page_in_lesson là số trang 1-based bên trong PDF bài học.
- Nếu end_page_in_lesson không xác định, dùng cùng giá trị với start_page_in_lesson.

JSON cần đúng shape sau:
{{
  "chunks": [
    {{
      "heading": "1.",
      "title": "Mệnh đề",
      "start_page_in_lesson": 1,
      "end_page_in_lesson": 2
    }}
  ]
}}
""".strip()
