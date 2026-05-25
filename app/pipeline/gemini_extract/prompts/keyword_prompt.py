"""Prompt builder for textbook PDF keyword extraction."""

from __future__ import annotations


def build_keyword_prompt(
    keyword_limit: int,
    source_type: str,
    source_title: str | None = None,
) -> str:
    title_line = (
        f"Nguồn nội dung có tiêu đề: {source_title}."
        if source_title
        else "Nguồn nội dung không có tiêu đề riêng."
    )

    return f"""
Bạn là hệ thống trích xuất từ khóa cho sách giáo khoa.

Bạn sẽ nhận một PDF segment từ sách giáo khoa. Segment này có loại nguồn: {source_type}.
{title_line}

NHIỆM VỤ:
- Trích xuất tối đa {keyword_limit} từ khóa hoặc cụm khái niệm quan trọng nhất.
- Chỉ lấy keyword/khái niệm thật sự quan trọng trong nội dung chuyên môn.
- Ưu tiên cụm danh từ, thuật ngữ, khái niệm, tên quy trình, công cụ, mô hình, hiện tượng hoặc nội dung trọng tâm.
- Giữ nguyên dấu tiếng Việt.
- Mỗi keyword nên ngắn gọn, không phải câu dài.
- Không lấy các từ chung chung như: bài học, học sinh, hoạt động, câu hỏi, ví dụ, hình, bảng, luyện tập, vận dụng.
- Không lặp keyword cùng nghĩa chỉ khác viết hoa/viết thường.
- Mỗi keyword phải có reason ngắn giải thích vì sao quan trọng.

YÊU CẦU OUTPUT:
- Chỉ trả JSON thuần, không markdown, không code fence, không giải thích ngoài JSON.
- Trả về đúng object theo schema sau:

{{
  "keywords": [
    {{
      "keyword": "...",
      "reason": "..."
    }}
  ]
}}
""".strip()
