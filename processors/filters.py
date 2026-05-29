from __future__ import annotations

import re
from typing import Any


BUDGET_KEYWORDS = (
    "budget",
    "campaign_budget",
    "daily_budget",
    "일 예산",
    "일예산",
    "예산",
)
DAILY_BUDGET_KEYWORDS = (
    "daily_budget",
    "일 예산",
    "일예산",
    "하루예산",
    "예산",
    "amount_micros",
)

CONTENT_MEDIA_BID_KEYWORDS = (
    "콘텐츠 매체 전용입찰가",
    "컨텐츠 매체 전용입찰가",
)

IMPACT_KEYWORDS = (
    "bidding_strategy",
    "입찰전략",
    "target_cpa",
    "tcpa",
    "목표 cpa",
    "목표값",
    "cpc_bid",
    "max_cpc",
    "입찰가",
    "bid",
    "keyword",
    "키워드",
    "negative",
    "제외",
    "ad_group_ad",
    "소재",
    "creative",
    "asset",
    "final_url",
    "final_urls",
    "tracking_url",
    "랜딩",
    "url",
    "status",
    "paused",
    "enabled",
    "on",
    "off",
    "중지",
    "활성",
    "일시중지",
    "seasonality",
    "시즌성",
    "시즌성 조정",
    "전환율 조정",
    "conversion rate adjustment",
)

NAME_ONLY_KEYWORDS = ("name", "이름", "명칭")
MEANINGLESS_SAVE_KEYWORDS = ("저장", "save", "saved")
SYSTEM_ACTOR_KEYWORDS = (
    "api",
    "system",
    "시스템",
    "자동",
    "google ads",
    "naver(api)",
    "dreamful7:naver(api)",
)
REVIEW_STATUS_KEYWORDS = (
    "소재 검수",
    "키워드 검토",
    "검토 상태",
    "검수",
    "심사",
)
LOW_IMPACT_GOOGLE_KEYWORDS = (
    "내 데이터 기반 세그먼트",
    "사용자가 업로드",
    "customer list",
    "user list",
)


def apply_raw_filters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if should_keep_raw(row)]


def should_keep_raw(row: dict[str, Any]) -> bool:
    media = str(row.get("매체", ""))
    actor = str(row.get("변경자", ""))
    change_type = str(row.get("변경유형", ""))
    text = _row_text(row)

    if is_system_actor(actor):
        return False

    if is_review_status_change(row):
        return False

    if media in {"구글SA", "구글AC"} and _contains_any(text, LOW_IMPACT_GOOGLE_KEYWORDS):
        return False

    if is_content_media_bid_setting_change(row):
        return True

    if is_budget_change(row):
        return is_new_daily_budget_setting(row)

    if _is_name_only(row, text):
        return False

    if _is_meaningless_save(text):
        return False

    return True


def is_content_media_bid_setting_change(row: dict[str, Any]) -> bool:
    return _contains_any(_row_text(row), CONTENT_MEDIA_BID_KEYWORDS)


def is_system_actor(actor: Any) -> bool:
    text = str(actor or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in SYSTEM_ACTOR_KEYWORDS)


def is_review_status_change(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    if not _contains_any(text, REVIEW_STATUS_KEYWORDS):
        return False
    change_type = str(row.get("변경유형", "")).lower()
    content = str(row.get("변경내용", "")).lower()
    if _contains_any(
        f"{change_type} {content}",
        ("소재 추가", "키워드 추가", "등록된 내용", "create", "created"),
    ):
        return False
    return True


def is_budget_change(row: dict[str, Any]) -> bool:
    return _is_budget_only(row, _row_text(row))


def is_new_daily_budget_setting(row: dict[str, Any]) -> bool:
    if not is_budget_change(row):
        return False
    old_value, new_value = daily_budget_values(row)
    return _is_empty_budget_value(old_value) and _is_positive_budget_value(new_value)


def daily_budget_summary_value(row: dict[str, Any]) -> str:
    return _display_budget_value(daily_budget_values(row)[1])


def daily_budget_values(row: dict[str, Any]) -> tuple[str, str]:
    old_value = _budget_value_from_cell(row.get("이전값", ""))
    new_value = _budget_value_from_cell(row.get("변경값", ""))
    if old_value or new_value:
        return old_value, new_value

    content = str(row.get("변경내용", "") or "")
    before_block, after_block = _change_blocks(content)
    old_value = _budget_value_from_text(before_block)
    new_value = _budget_value_from_text(after_block)
    if old_value or new_value:
        return old_value, new_value

    text = _row_text(row)
    before_block, after_block = _change_blocks(text)
    return _budget_value_from_text(before_block), _budget_value_from_text(after_block)


def _is_budget_only(row: dict[str, Any], text: str) -> bool:
    field = str(row.get("변경필드", "")).lower()
    change_type = str(row.get("변경유형", "")).lower()
    change_text = _strip_entity_names(row, text)
    if "campaign_budget" in change_type:
        return True
    if not _contains_any(change_text, BUDGET_KEYWORDS):
        return False

    # 입찰전략 필드명에는 bid가 들어갈 수 있어 budget 단독 변경만 제외한다.
    impact_without_budget = tuple(
        keyword for keyword in IMPACT_KEYWORDS if keyword not in {"bid", "status", "on", "off"}
    )
    if _contains_any(change_text.replace("budget", ""), impact_without_budget):
        return False

    budget_field_markers = ("budget", "일예산", "예산", "amount_micros")
    return _contains_any(field, budget_field_markers) or _contains_any(change_text, BUDGET_KEYWORDS)


def _is_name_only(row: dict[str, Any], text: str) -> bool:
    field_text = str(row.get("변경필드", "")).lower().strip()
    if not _contains_any(text, NAME_ONLY_KEYWORDS):
        return False
    if _contains_any(text, IMPACT_KEYWORDS):
        return False
    if not field_text:
        return True
    fields = [field.strip() for field in field_text.split(",") if field.strip()]
    return bool(fields) and all(field.endswith(".name") or field == "name" for field in fields)


def _is_meaningless_save(text: str) -> bool:
    if not _contains_any(text, MEANINGLESS_SAVE_KEYWORDS):
        return False
    return not _contains_any(text, IMPACT_KEYWORDS)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _row_text(row: dict[str, Any]) -> str:
    values = [
        row.get("변경레벨", ""),
        row.get("변경유형", ""),
        row.get("변경작업", ""),
        row.get("변경필드", ""),
        row.get("이전값", ""),
        row.get("변경값", ""),
        row.get("변경내용", ""),
        row.get("원본리소스명", ""),
        row.get("raw_text", ""),
    ]
    return " ".join(str(value) for value in values if value is not None)


def _strip_entity_names(row: dict[str, Any], text: str) -> str:
    stripped = str(text or "")
    for key in ("캠페인명", "광고그룹명", "소재명", "키워드명"):
        value = str(row.get(key, "") or "").strip()
        if len(value) < 2:
            continue
        stripped = re.sub(re.escape(value), " ", stripped, flags=re.I)
    return stripped


def _change_blocks(text: str) -> tuple[str, str]:
    before = ""
    after = ""
    match = re.search(r"변경\s*전(?P<before>.*?)(?:변경\s*후(?P<after>.*))?$", text, re.S)
    if match:
        before = match.group("before") or ""
        after = match.group("after") or ""
    return before, after


def _budget_value_from_cell(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _budget_value_from_text(text) or text


def _budget_value_from_text(text: str) -> str:
    if not text:
        return ""

    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    for line in reversed(lines):
        if not _contains_any(line, DAILY_BUDGET_KEYWORDS):
            continue
        if "사용여부" in line:
            continue
        value = _value_after_colon(line)
        if value:
            return value

    match = re.search(
        r"(?:daily_budget|일\s*예산|일예산|하루예산|예산|amount_micros)"
        r"[^0-9가-힣]*(?P<value>미설정|없음|null|none|[-\d,]+(?:\.\d+)?\s*(?:원|micros)?)",
        text,
        re.I,
    )
    if match:
        return match.group("value").strip()

    text_stripped = str(text).strip()
    return text_stripped if _looks_like_budget_value(text_stripped) else ""


def _value_after_colon(line: str) -> str:
    if ":" in line:
        return line.split(":", 1)[1].strip()
    if "：" in line:
        return line.split("：", 1)[1].strip()
    return ""


def _is_empty_budget_value(value: str) -> bool:
    normalized = _normalize_budget_value(value)
    if normalized in {"", "0", "0원", "0micros", "none", "null", "미설정", "없음", "사용안함", "-"}:
        return True
    number = _budget_number(normalized)
    return number == 0 if number is not None else False


def _is_positive_budget_value(value: str) -> bool:
    normalized = _normalize_budget_value(value)
    if not normalized or normalized in {"none", "null", "미설정", "없음", "사용안함", "-"}:
        return False
    number = _budget_number(normalized)
    return number > 0 if number is not None else True


def _display_budget_value(value: str) -> str:
    text = str(value or "").strip()
    number = _budget_number(text)
    if number is None:
        return text
    if number.is_integer():
        return f"{int(number):,}원"
    return f"{number:,.2f}원"


def _normalize_budget_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _budget_number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", str(value or ""))
    if cleaned in {"", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _looks_like_budget_value(value: str) -> bool:
    if not value:
        return False
    if _normalize_budget_value(value) in {"none", "null", "미설정", "없음", "사용안함", "0", "0원"}:
        return True
    return _budget_number(value) is not None
