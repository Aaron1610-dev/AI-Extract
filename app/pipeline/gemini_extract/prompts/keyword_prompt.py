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
Bạn là trợ lý trích xuất dữ liệu cho sách giáo khoa tiếng Việt.

Bạn sẽ nhận một PDF segment từ sách giáo khoa. Segment này có loại nguồn: {source_type}.
{title_line}

NHIỆM VỤ:
- BẮT BUỘC trả về đúng chính xác {keyword_limit} từ khóa hoặc cụm khái niệm quan trọng nhất.
- Không trả ít hơn {keyword_limit}.
- Không trả nhiều hơn {keyword_limit}.
- Chỉ lấy keyword/khái niệm thật sự quan trọng trong nội dung chuyên môn.
- Mỗi từ khóa nên là 1-6 từ, tiếng Việt có dấu nếu cần.
- Ưu tiên: khái niệm chuyên môn, thuật ngữ, công cụ, thao tác/quy trình, mô hình, hiện tượng, công thức, kí hiệu, cú pháp, thành phần hệ thống hoặc nội dung trọng tâm.
- Nếu PDF segment có ít khái niệm chính hiển nhiên, vẫn phải đủ {keyword_limit} bằng cách lấy thêm tiểu khái niệm, kí hiệu, định nghĩa, ví dụ tiêu biểu hoặc thuật ngữ liên quan được nêu rõ trong PDF.
- Không bịa khái niệm không xuất hiện trong PDF.
- Giữ nguyên dấu tiếng Việt.
- Giữ nguyên kí hiệu toán học nếu là keyword quan trọng.
- Không lấy các từ chung chung như: bài học, học sinh, hoạt động, câu hỏi, ví dụ, hình, bảng, luyện tập, vận dụng.
- Không lặp keyword giống hệt nhau. Các cụm như "Mệnh đề", "Mệnh đề toán học", "Mệnh đề chứa biến" là các keyword khác nhau nếu đều xuất hiện và có ý nghĩa riêng trong PDF.
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
Bạn là trợ lý trích xuất dữ liệu cho sách giáo khoa tiếng Việt.

Bạn sẽ nhận lại cùng một PDF segment từ sách giáo khoa. Segment này có loại nguồn: {source_type}.
{title_line}

Kết quả trước đó chỉ có {len(existing_keywords)}/{keyword_limit} keyword hợp lệ.
Existing keywords: {existing_json}

NHIỆM VỤ:
- BẮT BUỘC trích xuất đúng chính xác {missing_count} keyword bổ sung, phân biệt, có ý nghĩa từ PDF.
- Không lặp lại bất kỳ existing keyword nào.
- Không trả ít hơn {missing_count}.
- Không trả nhiều hơn {missing_count}.
- Chỉ trả về các keyword bổ sung còn thiếu, không trả lại danh sách đầy đủ.
- Nếu còn ít khái niệm chính, hãy dùng tiểu khái niệm, kí hiệu, định nghĩa, ví dụ tiêu biểu hoặc thuật ngữ liên quan được nêu rõ trong PDF để đủ {missing_count}.
- Không bịa khái niệm không xuất hiện trong PDF.
- Ưu tiên cụm danh từ/cụm khái niệm tiếng Việt ngắn gọn, khoảng 1-6 từ.
- Giữ nguyên dấu tiếng Việt và kí hiệu toán học nếu quan trọng.
- Tránh keyword chung chung.
- Không loại các cụm có quan hệ bao quát/chi tiết nếu chúng là khái niệm riêng trong PDF, ví dụ "Mệnh đề", "Mệnh đề toán học", "Mệnh đề chứa biến".
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
