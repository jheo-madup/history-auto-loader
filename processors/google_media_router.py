from __future__ import annotations

import re
from typing import Any


AC_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bp[\s_-]?max\b",
        r"\bperformance[\s_-]?max\b",
        r"\bperf[\s_-]?max\b",
        r"실적\s*최대화",
        r"앱\s*캠페인",
        r"\bapp[\s_-]?campaign\b",
        r"\buniversal[\s_-]?app\b",
        r"\buac\b",
        r"\baci\b",
        r"\baos\b",
        r"\bios\b",
        r"\bandroid\b",
        r"(?:^|[\s_\-\[\]()/])앱(?:$|[\s_\-\[\]()/])",
    )
)


def route_google_media(rows: list[dict[str, Any]], ac_customer_ids: set[str]) -> list[dict[str, Any]]:
    routed: list[dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        updated["매체"] = classify_google_media(updated, ac_customer_ids)
        routed.append(updated)
    return routed


def classify_google_media(row: dict[str, Any], ac_customer_ids: set[str]) -> str:
    account_id = _digits(row.get("계정ID", ""))
    text = " ".join(
        str(row.get(key, ""))
        for key in (
            "계정명",
            "캠페인명",
            "광고그룹명",
            "변경레벨",
            "변경유형",
            "변경필드",
            "변경내용",
            "원본리소스명",
            "raw_text",
        )
    ).lower()

    if account_id in ac_customer_ids:
        return "구글AC"
    if any(pattern.search(text) for pattern in AC_PATTERNS):
        return "구글AC"
    return "구글SA"


def _digits(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())
