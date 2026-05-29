from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from processors.filters import (
    daily_budget_summary_value,
    is_content_media_bid_setting_change,
    is_new_daily_budget_setting,
    should_keep_raw,
)


VALUE_SENSITIVE_LABELS = (
    "tCPA/목표값 변경",
    "입찰가 변경",
    "랜딩 URL 변경",
    "제외 데이터 세그먼트 추가",
)
VALUE_SENSITIVE_LABEL_PREFIXES = ("콘텐츠 매체 전용입찰가",)
ALWAYS_COUNT_LABEL_PREFIXES = ("소재 ON", "소재 OFF")
MAX_SUMMARY_LINES = 30
AUTO_BID_CHANGE_TYPE = "자동입찰 목표순위 변경"


def build_summary(rows: list[dict[str, Any]], media: str) -> str:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        if row.get("매체") != media:
            continue
        if not should_keep_raw(row):
            continue
        dedupe_key = _dedupe_key(row)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        classified = _classify(row)
        if classified is None:
            continue
        priority, label = classified
        entity = _entity_for_label(row, label)
        if entity == "미분류":
            continue
        candidates.append((priority, label, {**row, "_summary_entity": entity}))

    candidates.sort(
        key=lambda item: (
            item[0],
            str(item[2].get("변경일시", "")),
            item[1],
            item[2].get("_summary_entity", ""),
        )
    )

    aggregate_lines, aggregate_indexes = _asset_aggregate_lines(candidates)
    grouped: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for index, (priority, label, row) in enumerate(candidates):
        if index in aggregate_indexes:
            continue
        key = (row["_summary_entity"], label, _group_detail(row, label))
        if key not in grouped:
            grouped[key] = {
                "priority": priority,
                "label": label,
                "entity": row["_summary_entity"],
                "count": 0,
                "row": row,
            }
        grouped[key]["count"] += _event_count_for_label(row, label)

    lines: list[str] = [line for _, line in sorted(aggregate_lines, key=lambda item: item[0])]
    for item in sorted(grouped.values(), key=lambda value: value["priority"]):
        lines.append(_line(item))
        if len(lines) >= MAX_SUMMARY_LINES:
            break

    return "\n".join(lines)


def _classify(row: dict[str, Any]) -> tuple[int, str] | None:
    change_text = _classification_text(row)
    if str(row.get("변경유형", "")).strip() == AUTO_BID_CHANGE_TYPE:
        return 3, AUTO_BID_CHANGE_TYPE
    if is_new_daily_budget_setting(row):
        return 3, "일예산 신규 설정"
    if is_content_media_bid_setting_change(row):
        status = _content_media_bid_status(row)
        return 3, f"콘텐츠 매체 전용입찰가 {status}" if status else "콘텐츠 매체 전용입찰가 변경"
    if _contains_any(change_text, ("budget", "일예산", "예산")) and not _contains_any(
        change_text, ("bidding_strategy", "입찰전략", "tcpa", "입찰가", "bid")
    ):
        return None
    if _contains_any(change_text, ("name", "이름", "명칭")) and not _contains_any(
        change_text,
        (
            "keyword",
            "키워드",
            "url",
            "status",
            "입찰",
            "tcpa",
            "시즌성",
            "전환율 조정",
            "creative",
            "asset",
            "소재",
            "ad set",
            "adset",
            "광고세트",
            "광고 세트",
        ),
    ):
        return None

    if _contains_any(change_text, ("bidding_strategy", "입찰전략", "bid strategy")):
        return 1, "입찰전략 변경"
    if _contains_any(change_text, ("seasonality", "시즌성", "시즌성 조정", "전환율 조정")):
        return 2, "시즌성 조정"
    if _is_bid_change(row, change_text):
        return 3, "입찰가 변경"
    if _is_keyword_change(row, change_text):
        return 4, "키워드 추가/제외"
    asset_status = _asset_status(row)
    if asset_status and _is_asset_change(row, change_text):
        return 5, f"소재 {asset_status}"
    if _is_asset_change(row, change_text):
        return 5, "소재 추가/중지/교체"
    if _is_target_cpa_change(row):
        return 2, "tCPA/목표값 변경"
    if _contains_any(change_text, ("final_url", "final_urls", "tracking_url", "랜딩", "url")):
        return 6, "랜딩 URL 변경"
    if _is_excluded_data_segment_change(change_text):
        return 7, "제외 데이터 세그먼트 추가"
    if _is_campaign_status_change(row, change_text):
        return 8, "캠페인 ON/OFF"
    if _is_ad_group_status_change(row, change_text):
        return 9, "광고그룹 ON/OFF"
    if _contains_any(change_text, ("create", "remove", "생성", "삭제", "구조", "실험 상태")):
        return 10, "캠페인/그룹 구조 변경"
    return None


def _line(item: dict[str, Any]) -> str:
    entity = item["entity"]
    label = item["label"]
    count = item["count"]
    row = item["row"]
    suffix = "" if _always_count_label(label) else _change_suffix(row)

    if label == AUTO_BID_CHANGE_TYPE:
        return _auto_bid_line(row)
    if label == "일예산 신규 설정":
        return f"[{entity}] 일예산 신규 설정: {daily_budget_summary_value(row)}"
    if count > 1 or _always_count_label(label):
        if suffix:
            return f"[{entity}] {label} {count}건 ({suffix})"
        return f"[{entity}] {label} {count}건"
    if suffix:
        return f"[{entity}] {label} ({suffix})"
    return f"[{entity}] {label}"


def _change_suffix(row: dict[str, Any]) -> str:
    segment_suffix = _data_segment_suffix(row)
    if segment_suffix:
        return segment_suffix

    target_suffix = _target_value_suffix(row)
    if target_suffix:
        return target_suffix

    content_bid_suffix = _usage_change_suffix(row, "콘텐츠 매체 전용입찰가 사용여부")
    if content_bid_suffix:
        return content_bid_suffix

    old_value = _clean_value(row.get("이전값", ""))
    new_value = _clean_value(row.get("변경값", ""))
    if old_value and new_value and old_value != new_value:
        return f"{old_value} -> {new_value}"
    content = _clean_value(row.get("변경내용", ""))
    if content and len(content) <= 45 and not content.startswith("{"):
        return content
    return ""


def _group_detail(row: dict[str, Any], label: str) -> str:
    if label in VALUE_SENSITIVE_LABELS or _starts_with_any(label, VALUE_SENSITIVE_LABEL_PREFIXES):
        return _change_suffix(row)
    return ""


def _always_count_label(label: str) -> bool:
    return _starts_with_any(label, ALWAYS_COUNT_LABEL_PREFIXES)


def _data_segment_suffix(row: dict[str, Any]) -> str:
    text = _row_text(row)
    if not _is_excluded_data_segment_change(text):
        return ""

    content = str(row.get("변경내용", "") or "")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) >= 2:
        return _clean_segment_name(lines[1])

    match = re.search(r"([^\n]+?\(제외됨\))", text)
    if match:
        return _clean_segment_name(match.group(1))
    return ""


def _clean_segment_name(value: str) -> str:
    text = value.strip()
    text = re.sub(r"\s*\(제외됨\)\s*$", "", text)
    return text if len(text) <= 80 else f"{text[:77]}..."


def _target_value_suffix(row: dict[str, Any]) -> str:
    text = _classification_text(row)
    if not _contains_any(text, ("target_cpa", "tcpa", "타겟 cpa", "목표 cpa", "목표값")):
        return ""

    match = re.search(
        r"(?:타겟\s*CPA|목표\s*CPA|tCPA|target\s*CPA)"
        r"[^\d₩$€¥-]*"
        r"(?P<old>[₩$€¥]?\s*-?[\d,]+(?:\.\d+)?%?)"
        r"\s*(?:에서|from|->|→|to)\s*"
        r"(?P<new>[₩$€¥]?\s*-?[\d,]+(?:\.\d+)?%?)",
        text,
        re.I,
    )
    if not match:
        return ""

    old_value = _normalize_amount(match.group("old"))
    new_value = _normalize_amount(match.group("new"))
    direction = _change_direction(old_value, new_value)
    return f"{old_value} -> {new_value}{f' {direction}' if direction else ''}"


def _normalize_amount(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _change_direction(old_value: str, new_value: str) -> str:
    old_number = _amount_number(old_value)
    new_number = _amount_number(new_value)
    if old_number is None or new_number is None or old_number == new_number:
        return ""
    return "상향" if new_number > old_number else "하향"


def _amount_number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if cleaned in {"", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_bid_change(row: dict[str, Any], text: str) -> bool:
    field = str(row.get("변경필드", "")).lower()
    if _contains_any(field, ("cpc_bid", "max_cpc", "입찰가")):
        return True
    return _contains_any(text, ("cpc_bid", "max_cpc", "입찰가")) and not _contains_any(
        text, ("bidding_strategy", "입찰전략", "target_cpa", "tcpa", "목표 cpa", "타겟 cpa")
    )


def _is_keyword_change(row: dict[str, Any], text: str) -> bool:
    field = str(row.get("변경필드", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    level = str(row.get("변경레벨", "")).lower()
    keyword_name = str(row.get("키워드명", "")).strip()
    if keyword_name:
        return True
    keyword_context = _contains_any(
        " ".join((field, change_type, level, text.lower())),
        ("keyword", "키워드", "negative_keyword", "검색어"),
    )
    return keyword_context and not _is_excluded_data_segment_change(text)


def _is_asset_change(row: dict[str, Any], text: str) -> bool:
    field = str(row.get("변경필드", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    level = str(row.get("변경레벨", "")).lower()
    return _contains_any(
        " ".join((field, change_type, level, text.lower())),
        (
            "ad_group_ad",
            "creative",
            "asset",
            "소재",
            "애셋",
            "이미지",
            "동영상",
            "반응형 검색 광고",
            "검색 광고",
            "responsive search ad",
        ),
    )


def _asset_status(row: dict[str, Any]) -> str:
    change_type = str(row.get("변경유형", "")).lower()
    operation = str(row.get("변경작업", "")).lower()
    if "on/off" not in f"{change_type} {operation}":
        return _changed_status(row)
    return _changed_on_off_status(row) or _changed_status(row)


def _asset_aggregate_lines(
    candidates: list[tuple[int, str, dict[str, Any]]],
) -> tuple[list[tuple[int, str]], set[int]]:
    grouped: OrderedDict[tuple[str, str, str], list[int]] = OrderedDict()
    for index, (_, label, row) in enumerate(candidates):
        key = _asset_aggregate_key(label, row)
        if key is None:
            continue
        grouped.setdefault(key, []).append(index)

    lines: list[tuple[int, str]] = []
    aggregate_indexes: set[int] = set()
    for (entity, action, sort_key), indexes in grouped.items():
        total_count = sum(_event_count_for_label(candidates[index][2], candidates[index][1]) for index in indexes)
        if total_count < 3:
            continue
        aggregate_indexes.update(indexes)
        lines.append((5, f"[{entity}] 소재 {total_count}건 {action}"))
    return lines, aggregate_indexes


def _asset_aggregate_key(label: str, row: dict[str, Any]) -> tuple[str, str, str] | None:
    if not label.startswith("소재 "):
        return None
    level = str(row.get("변경레벨", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    if not _contains_any(
        f"{level} {change_type}",
        ("소재", "ad_group_ad", "creative", "asset", "반응형 검색 광고", "검색 광고"),
    ):
        return None

    ad_group = str(row.get("광고그룹명", "")).strip()
    campaign = str(row.get("캠페인명", "")).strip()
    entity = ad_group or campaign
    if not entity:
        return None

    action = _asset_action(row, label)
    sort_key = "|".join((str(row.get("매체", "")), campaign, ad_group, action))
    return entity, action, sort_key


def _asset_action(row: dict[str, Any], label: str) -> str:
    text = _row_text(row)
    if _contains_any(text, ("추가", "create", "created", "등록된 내용")):
        return "추가"
    if _contains_any(text, ("삭제", "remove", "removed")):
        return "삭제"
    return "변경"


def _content_media_bid_status(row: dict[str, Any]) -> str:
    new_usage = _changed_usage_value(row, "콘텐츠 매체 전용입찰가 사용여부")
    if new_usage == "사용함":
        return "ON"
    if new_usage == "사용안함":
        return "OFF"
    return ""


def _usage_change_suffix(row: dict[str, Any], label: str) -> str:
    old_usage, new_usage = _changed_usage_values(row, label)
    if old_usage and new_usage and old_usage != new_usage:
        return f"{old_usage} -> {new_usage}"
    return ""


def _changed_usage_value(row: dict[str, Any], label: str) -> str:
    return _changed_usage_values(row, label)[1]


def _changed_usage_values(row: dict[str, Any], label: str) -> tuple[str, str]:
    pattern = (
        rf"변경\s*전\s*{re.escape(label)}\s*:\s*(?P<old>사용함|사용안함)"
        rf"\s*변경\s*후\s*{re.escape(label)}\s*:\s*(?P<new>사용함|사용안함)"
    )
    match = re.search(pattern, _row_text(row), re.S)
    if not match:
        return "", ""
    return match.group("old"), match.group("new")


def _changed_on_off_status(row: dict[str, Any]) -> str:
    match = re.search(r"변경\s*후\s*On/Off\s*:\s*(ON|OFF)", _row_text(row), re.I | re.S)
    return match.group(1).upper() if match else ""


def _changed_status(row: dict[str, Any]) -> str:
    text = _classification_text(row).lower()
    if re.search(r"(?:에서|->|→)\s*(?:일시\s*중지|일시중지|중지|paused|off)", text):
        return "OFF"
    if re.search(r"(?:변경\s*후|after)[^\n]*(?:일시\s*중지|일시중지|중지|paused|off)", text):
        return "OFF"
    if re.search(r"(?:에서|->|→)\s*(?:운영중|운영\s*중|활성|enabled|on)", text):
        return "ON"
    if re.search(r"(?:변경\s*후|after)[^\n]*(?:운영중|운영\s*중|활성|enabled|on)", text):
        return "ON"
    return ""


def _is_target_cpa_change(row: dict[str, Any]) -> bool:
    return _contains_any(_classification_text(row), ("target_cpa", "tcpa", "타겟 cpa", "목표 cpa", "목표값"))


def _event_count_for_label(row: dict[str, Any], label: str) -> int:
    if label.startswith("소재 "):
        return _asset_event_count(row)
    return 1


def _asset_event_count(row: dict[str, Any]) -> int:
    text = str(row.get("변경내용", "") or row.get("raw_text", "") or "")
    matches = re.findall(
        r"(?:반응형\s*검색\s*광고|검색\s*광고|소재|광고)\s*(\d+)\s*개(?:가|이)?\s*변경",
        text,
        re.I,
    )
    total = sum(int(match) for match in matches if match.isdigit())
    return max(1, total)


def _auto_bid_line(row: dict[str, Any]) -> str:
    keyword = str(row.get("키워드명", "") or row.get("_summary_entity", "")).strip()
    old_rank = _rank_text(row.get("이전값", ""))
    new_rank = _rank_text(row.get("변경값", ""))
    if old_rank and new_rank:
        return f"[{keyword}] 목표순위 {old_rank} → {new_rank} 변경"
    if new_rank:
        return f"[{keyword}] 목표순위 {new_rank}로 변경"
    return f"[{keyword}] 목표순위 변경"


def _rank_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if "순위" in text else f"{text}순위"


def _is_excluded_data_segment_change(text: str) -> bool:
    return _contains_any(
        text,
        (
            "제외 데이터 세그먼트",
            "excluded data segment",
            "audience exclusion",
            "잠재고객 제외",
        ),
    )


def _is_campaign_status_change(row: dict[str, Any], text: str) -> bool:
    level = str(row.get("변경레벨", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    has_campaign_context = _contains_any(" ".join((level, change_type, text.lower())), ("campaign", "캠페인"))
    has_status_context = _contains_any(text, ("status", "paused", "enabled", "on", "off", "중지", "활성", "일시중지", "운영중"))
    return has_campaign_context and has_status_context


def _is_ad_group_status_change(row: dict[str, Any], text: str) -> bool:
    level = str(row.get("변경레벨", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    has_group_context = _contains_any(
        " ".join((level, change_type, text.lower())),
        ("ad_group", "ad set", "adset", "광고그룹", "광고세트", "광고 세트"),
    )
    has_status_context = _contains_any(text, ("status", "paused", "enabled", "on", "off", "중지", "활성", "일시중지", "운영중"))
    return has_group_context and has_status_context


def _entity(row: dict[str, Any]) -> str:
    override = str(row.get("_summary_entity_override", "")).strip()
    if override:
        return override
    for key in ("광고그룹명", "캠페인명", "키워드명", "소재명", "계정명", "계정ID"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    resource = str(row.get("원본리소스명", "")).strip()
    if resource:
        return resource.rsplit("/", 1)[-1]
    return "미분류"


def _entity_for_label(row: dict[str, Any], label: str) -> str:
    if label == "일예산 신규 설정":
        for key in ("캠페인명", "광고그룹명", "계정명", "계정ID"):
            value = str(row.get(key, "")).strip()
            if value:
                return value
        return "미분류"
    if label == AUTO_BID_CHANGE_TYPE:
        value = str(row.get("키워드명", "")).strip()
        return value or _entity(row)
    return _entity(row)


def _clean_value(value: Any) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if not text or len(text) > 80:
        return ""
    return text


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _starts_with_any(text: str, prefixes: tuple[str, ...]) -> bool:
    return any(text.startswith(prefix) for prefix in prefixes)


def _dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    fields = (
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
    )
    return tuple(str(row.get(field, "") or "").strip().replace("\r\n", "\n") for field in fields)


def _row_text(row: dict[str, Any]) -> str:
    values = [
        row.get("변경레벨", ""),
        row.get("변경유형", ""),
        row.get("변경작업", ""),
        row.get("변경필드", ""),
        row.get("이전값", ""),
        row.get("변경값", ""),
        row.get("변경내용", ""),
        row.get("raw_text", ""),
    ]
    return " ".join(str(value) for value in values if value is not None)


def _classification_text(row: dict[str, Any]) -> str:
    return _strip_entity_names(row, _row_text(row))


def _strip_entity_names(row: dict[str, Any], text: str) -> str:
    stripped = str(text or "")
    for key in ("캠페인명", "광고그룹명", "소재명", "키워드명"):
        value = str(row.get(key, "") or "").strip()
        if len(value) < 2:
            continue
        stripped = re.sub(re.escape(value), " ", stripped, flags=re.I)
    return stripped
