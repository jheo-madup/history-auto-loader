from __future__ import annotations

import hashlib
from typing import Any


HASH_FIELDS = [
    "변경일시",
    "변경자",
    "캠페인명",
    "광고그룹명",
    "소재명",
    "키워드명",
    "변경유형",
    "변경필드",
    "변경내용",
    "원본리소스명",
]

BID_SHEET_HASH_FIELDS = [
    "_hash_source",
    "일자",
    "_auto_bid_keyword_id",
    "키워드명",
    "캠페인명",
    "광고그룹명",
    "이전값",
    "변경값",
    "변경필드",
]


def build_row_hash(row: dict[str, Any]) -> str:
    fields = BID_SHEET_HASH_FIELDS if _is_bid_sheet_row(row) else HASH_FIELDS
    seed = "||".join(_normalize(row.get(field, "")) for field in fields)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def attach_row_hash(row: dict[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    updated["row_hash"] = build_row_hash(updated)
    return updated


def _normalize(value: Any) -> str:
    return str(value or "").strip().replace("\r\n", "\n")


def _is_bid_sheet_row(row: dict[str, Any]) -> bool:
    if str(row.get("_hash_source", "")).strip() in {"bid_sheet", "auto_bid_sheet"}:
        return True
    raw_text = str(row.get("raw_text", ""))
    return "source=bid_sheet" in raw_text or "source=auto_bid_sheet" in raw_text
