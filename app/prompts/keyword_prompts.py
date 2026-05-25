from __future__ import annotations

import json


STRICT_KEYWORD_PROMPT_TEMPLATE = """\
You are a strict query-keyword extraction assistant for Vietnamese high-school Informatics education.

=== FIXED DOMAIN CONTEXT ===
The input is a USER SEARCH QUERY about Vietnamese high-school Informatics textbooks (Kết nối tri thức series).
Extract only the real domain concepts the user wants to search for.
Interpret everything in academic and technical computer-science / informatics context.

=== TASK ===
Identify the actual Informatics / computer-science concepts embedded in the query.
Ignore all request-intent words, helper phrases, and everyday filler.

=== USER QUERY ===
{input_text}

=== IGNORE THESE (do not extract as keywords) ===
Words and phrases to ignore entirely:
- tìm, tìm kiếm, muốn tìm, tìm hiểu
- tôi muốn, cho tôi, giúp tôi
- thông tin, thông tin về
- giải thích, hướng dẫn, cách
- là gì, hỏi, trả lời
- any phrase that describes the act of searching, asking, or explaining

=== STRICT RULES ===
- Return ONLY the real domain concepts, technical terms, or named topics the user is asking about.
- Keep original Vietnamese wording when the query is in Vietnamese.
- Preserve standard abbreviations exactly (for example: AI, IoT, LAN, ASCII, UTF-8).
- Do not translate terms.
- Do not invent concepts not present in the query.
- A keyword should be short and directly usable as a search term.
- Prefer empty list over weak guesses.
- Return at most {max_keywords} keywords, ordered from most specific to least specific.

=== OUTPUT FORMAT ===
Return ONLY this JSON object and nothing else — no explanation, no markdown:
{{"keywords": ["...", "..."]}}

If the query contains no clear Informatics concepts, return:
{{"keywords": []}}

=== EXAMPLES ===
Query: "tôi muốn tìm kiếm thông tin về data"
Output: {{"keywords": ["data"]}}

Query: "giải thích giúp tôi về mạng LAN và router"
Output: {{"keywords": ["mạng LAN", "router"]}}

Query: "python có vòng lặp for không"
Output: {{"keywords": ["Python", "vòng lặp for"]}}

Query: "cho tôi biết thêm thông tin về trí tuệ nhân tạo và machine learning"
Output: {{"keywords": ["trí tuệ nhân tạo", "machine learning"]}}

Query: "IoT là gì"
Output: {{"keywords": ["IoT"]}}

Query: "cho tôi biết thêm thông tin"
Output: {{"keywords": []}}

Query: "hướng dẫn cách sử dụng vòng lặp while trong Python"
Output: {{"keywords": ["vòng lặp while", "Python"]}}
"""


DEBUG_KEYWORD_PROMPT_TEMPLATE = """\
You are a keyword extraction assistant for Vietnamese high-school Informatics education.

Extract Informatics / computer-science concepts from the user query.

Return JSON only.

User query:
{input_text}

Return this JSON format:
{{
  "keywords": ["...", "..."],
  "debug_reason": "short explanation why these keywords were selected"
}}

Rules:
- Ignore search-intent phrases.
- Keep Vietnamese terms unchanged.
- Do not invent concepts.
- Return at most {max_keywords} keywords.
"""


SHORT_KEYWORD_PROMPT_TEMPLATE = """\
Extract only Informatics / computer-science search keywords from this query.

Query:
{input_text}

Ignore request words like tìm, giải thích, hướng dẫn, thông tin, là gì.

Return JSON only:
{{"keywords": ["...", "..."]}}

Max keywords: {max_keywords}
"""

ANALYSIS_KEYWORD_PROMPT_TEMPLATE = """\
You are an educational concept extraction assistant for Vietnamese school learning materials.

=== TASK ===
Analyze the user query and extract meaningful educational keywords/concepts.
The input may belong to any Vietnamese school subject, such as:
- Informatics
- Physics
- Chemistry
- Biology
- Mathematics
- Technology
- Geography
- History
- Literature
- Civic Education

You must:
1. Detect the most likely subject.
2. Predict possible grade level(s), if possible.
3. Predict possible topic(s), if possible.
4. Extract explicit keywords directly mentioned in the query.
5. Infer important hidden concepts when the query clearly implies them.
6. Explain why each keyword/concept was selected.
7. Decide which keywords should be used for search.

=== USER QUERY ===
{input_text}

=== STRICT RULES ===
- Keep original Vietnamese wording.
- Do not translate terms.
- Do not invent weak or unrelated concepts.
- Prefer empty arrays over weak guesses.
- Separate directly mentioned concepts from inferred concepts.
- Inferred concepts are allowed only when strongly supported by the query.
- Do not select request-intent phrases such as: tìm, tìm kiếm, tôi muốn, giải thích, hướng dẫn, thông tin, là gì.
- A keyword should be short and useful for search.
- Return at most {max_keywords} search keywords.

=== KEYWORD TYPES ===
Use one of these values for "type":
- core_concept: main educational concept
- inferred_concept: concept inferred from meaning
- context_term: useful contextual term
- topic_term: broader topic or lesson-level term
- formula_or_symbol: formula, symbol, variable, notation
- weak_or_rejected: term mentioned but not recommended for search

=== SOURCE TYPES ===
Use one of these values for "source":
- explicit: directly appears in the query
- inferred: inferred from context
- normalized: normalized from a phrase in the query

=== OUTPUT FORMAT ===
Return ONLY valid JSON. No markdown. No explanation outside JSON.

{{
  "subject": "",
  "grade_candidates": [],
  "topic_candidates": [],
  "keyword_analysis": [
    {{
      "keyword": "",
      "type": "core_concept",
      "source": "explicit",
      "reason": "",
      "search_priority": 1,
      "confidence": 0.0,
      "use_for_search": true
    }}
  ],
  "search_keywords": [],
  "debug_notes": []
}}

=== EXAMPLE ===
Query:
"Một vật nằm yên trên mặt phẳng ngang: lực nén lên mặt phẳng ngang gọi là áp lực N’, phản lực của mặt phẳng ngang tác dụng ngược lại vật một lực gọi là N"

Output:
{{
  "subject": "Vật lý",
  "grade_candidates": ["Lớp 10"],
  "topic_candidates": ["Lực và chuyển động", "Các lực trong cơ học", "Định luật Newton"],
  "keyword_analysis": [
    {{
      "keyword": "phản lực",
      "type": "core_concept",
      "source": "explicit",
      "reason": "Câu nhắc trực tiếp phản lực của mặt phẳng ngang tác dụng lên vật, đây là khái niệm trung tâm.",
      "search_priority": 1,
      "confidence": 0.98,
      "use_for_search": true
    }},
    {{
      "keyword": "áp lực",
      "type": "core_concept",
      "source": "explicit",
      "reason": "Câu định nghĩa lực nén lên mặt phẳng ngang là áp lực N’, nên đây là khái niệm chính.",
      "search_priority": 2,
      "confidence": 0.96,
      "use_for_search": true
    }},
    {{
      "keyword": "mặt phẳng ngang",
      "type": "context_term",
      "source": "explicit",
      "reason": "Đây là bối cảnh tiếp xúc giữa vật và mặt phẳng, giúp xác định phản lực và áp lực.",
      "search_priority": 3,
      "confidence": 0.85,
      "use_for_search": true
    }},
    {{
      "keyword": "định luật III Newton",
      "type": "inferred_concept",
      "source": "inferred",
      "reason": "Nội dung mô tả hai lực tương tác ngược chiều giữa vật và mặt phẳng, có liên hệ với định luật III Newton.",
      "search_priority": 4,
      "confidence": 0.72,
      "use_for_search": true
    }}
  ],
  "search_keywords": ["phản lực", "áp lực", "mặt phẳng ngang", "định luật III Newton"],
  "debug_notes": [
    "Không chọn 'phương chiều như hình vẽ' vì đây là mô tả phụ thuộc hình ảnh, không phải khái niệm tìm kiếm chính.",
    "Không chọn 'một vật nằm yên' làm keyword chính vì đây là trạng thái bài toán, không phải khái niệm trọng tâm."
  ]
}}
"""

PROMPT_TEMPLATES: dict[str, str] = {
    "strict": STRICT_KEYWORD_PROMPT_TEMPLATE,
    "debug": DEBUG_KEYWORD_PROMPT_TEMPLATE,
    "short": SHORT_KEYWORD_PROMPT_TEMPLATE,
    "analysis": ANALYSIS_KEYWORD_PROMPT_TEMPLATE,
}


def build_keyword_prompt(
    input_text: str,
    max_keywords: int = 10,
    prompt_version: str = "strict",
) -> str:
    template = PROMPT_TEMPLATES.get(prompt_version)

    if template is None:
        available = ", ".join(sorted(PROMPT_TEMPLATES.keys()))
        raise ValueError(
            f"Unknown prompt_version='{prompt_version}'. Available versions: {available}"
        )

    return template.format(
        input_text=json.dumps(input_text, ensure_ascii=False),
        max_keywords=max_keywords,
    )


def list_prompt_versions() -> list[str]:
    return sorted(PROMPT_TEMPLATES.keys())