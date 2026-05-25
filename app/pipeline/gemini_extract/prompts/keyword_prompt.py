"""Prompt builder for textbook PDF keyword extraction."""

from __future__ import annotations

import json


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
- BẮT BUỘC trả về chính xác {keyword_limit} từ khóa hoặc cụm khái niệm quan trọng nhất.
- Không trả ít hơn {keyword_limit}.
- Không trả nhiều hơn {keyword_limit}.
- Chỉ lấy keyword/khái niệm thật sự quan trọng trong nội dung chuyên môn.
- Ưu tiên cụm danh từ/cụm khái niệm tiếng Việt ngắn gọn, cụ thể theo nội dung SGK.
- Bao gồm các khái niệm chuyên môn, thuật ngữ, tên quy trình, công cụ, mô hình, hiện tượng hoặc nội dung trọng tâm.
- Nếu PDF segment có ít khái niệm hiển nhiên, hãy lấy thêm khái niệm liên quan, kí hiệu, tiểu khái niệm hoặc khái niệm nền tảng được nêu rõ trong PDF.
- Không bịa khái niệm không xuất hiện trong PDF.
- Giữ nguyên dấu tiếng Việt.
- Giữ nguyên kí hiệu toán học nếu là keyword quan trọng.
- Mỗi keyword nên ngắn gọn, không phải câu dài.
- Không lấy các từ chung chung như: bài học, học sinh, hoạt động, câu hỏi, ví dụ, hình, bảng, luyện tập, vận dụng.
- Không lặp keyword và tránh near-duplicate keywords chỉ khác viết hoa/viết thường hoặc diễn đạt quá sát nhau.
- Không trả giải thích, reason hoặc confidence.

YÊU CẦU OUTPUT:
- Chỉ trả JSON thuần, không markdown, không code fence, không giải thích ngoài JSON.
- Trả về đúng object theo schema sau:

{{
  "keywords": [
    {{
      "keyword_name": "..."
    }}
  ]
}}
""".strip()


def build_keyword_retry_prompt(
    *,
    keyword_limit: int,
    source_type: str,
    source_title: str | None,
    existing_keywords: list[str],
) -> str:
    missing_count = keyword_limit - len(existing_keywords)
    existing_json = json.dumps(existing_keywords, ensure_ascii=False)
    title_line = (
        f"Nguồn nội dung có tiêu đề: {source_title}."
        if source_title
        else "Nguồn nội dung không có tiêu đề riêng."
    )

    return f"""
Bạn là hệ thống trích xuất từ khóa cho sách giáo khoa.

Bạn sẽ nhận lại cùng một PDF segment từ sách giáo khoa. Segment này có loại nguồn: {source_type}.
{title_line}

Kết quả trước đó chỉ có {len(existing_keywords)}/{keyword_limit} keyword hợp lệ.
Existing keywords: {existing_json}

NHIỆM VỤ:
- BẮT BUỘC trích xuất chính xác {missing_count} keyword bổ sung, phân biệt, có ý nghĩa từ PDF.
- Không lặp lại bất kỳ existing keyword nào.
- Không trả ít hơn {missing_count}.
- Không trả nhiều hơn {missing_count}.
- Chỉ dùng khái niệm, kí hiệu, tiểu khái niệm hoặc khái niệm nền tảng được nêu rõ trong PDF.
- Không bịa khái niệm không xuất hiện trong PDF.
- Ưu tiên cụm danh từ/cụm khái niệm tiếng Việt ngắn gọn.
- Giữ nguyên dấu tiếng Việt và kí hiệu toán học nếu quan trọng.
- Tránh keyword chung chung và tránh near-duplicate.
- Không trả giải thích, reason hoặc confidence.

YÊU CẦU OUTPUT:
- Chỉ trả JSON thuần, không markdown, không code fence, không giải thích ngoài JSON.
- Trả về đúng object theo schema sau:

{{
  "keywords": [
    {{
      "keyword_name": "..."
    }}
  ]
}}
""".strip()
