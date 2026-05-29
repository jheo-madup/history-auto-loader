from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from utils.datetime_utils import parse_change_datetime


RAW_COLUMNS = [
    "수집일시",
    "조회시작일시",
    "조회종료일시",
    "일자",
    "매체",
    "계정ID",
    "계정명",
    "변경일시",
    "변경자",
    "캠페인명",
    "광고그룹명",
    "소재명",
    "키워드명",
    "변경레벨",
    "변경유형",
    "변경작업",
    "변경필드",
    "이전값",
    "변경값",
    "변경내용",
    "원본리소스명",
    "raw_text",
    "row_hash",
]


GOOGLE_LEVEL_MAP = {
    "CAMPAIGN": "캠페인",
    "AD_GROUP": "광고그룹",
    "AD_GROUP_AD": "소재",
    "AD_GROUP_ASSET": "소재",
    "AD_GROUP_CRITERION": "키워드",
    "CAMPAIGN_CRITERION": "캠페인 구조",
    "CAMPAIGN_BUDGET": "예산",
    "ASSET": "소재",
}


NAVER_ALIASES = {
    "account_id": ("계정ID", "계정 ID", "광고계정ID", "광고계정 ID", "customerId"),
    "account_name": ("계정명", "계정 이름", "광고계정명", "광고계정 이름"),
    "changed_at": (
        "변경일시",
        "변경 일시",
        "변경일자",
        "변경 일자",
        "일시",
        "작업일시",
        "등록일시",
        "시간",
    ),
    "changed_by": ("변경자", "작업자", "사용자", "수정자", "등록자"),
    "campaign": ("캠페인명", "캠페인 이름", "캠페인", "Campaign"),
    "ad_group": ("광고그룹명", "광고그룹 이름", "광고그룹", "Ad Group"),
    "ad": ("소재명", "소재 이름", "소재", "광고소재명"),
    "keyword": ("키워드명", "키워드 이름", "키워드"),
    "level": ("변경레벨", "구분", "대상", "변경대상"),
    "change_type": ("변경유형", "변경 유형", "이력유형", "작업유형", "유형"),
    "operation": ("변경작업", "작업", "액션", "상태"),
    "field": ("변경필드", "변경 필드", "항목", "변경항목"),
    "old_value": ("이전값", "기존값", "변경 전", "수정 전"),
    "new_value": ("변경값", "신규값", "변경 후", "수정 후"),
    "content": ("변경내용", "변경 내용", "상세내용", "상세 내용", "내용"),
    "resource": ("원본리소스명", "리소스명", "대상명", "원본"),
}


GOOGLE_BROWSER_ALIASES = {
    "account_id": ("계정ID", "계정 ID", "Customer ID", "CustomerID", "Account ID"),
    "account_name": ("계정명", "계정 이름", "Account", "Account name", "Customer"),
    "changed_at": (
        "변경일시",
        "변경 일시",
        "날짜 및 시간",
        "날짜",
        "시간",
        "Date / time",
        "Date and time",
        "Change time",
        "Time",
    ),
    "changed_by": ("변경자", "사용자", "작업자", "User", "Changed by"),
    "campaign": ("캠페인명", "캠페인", "Campaign", "Campaign name"),
    "ad_group": ("광고그룹명", "광고그룹", "Ad group", "Ad group name"),
    "ad": ("소재명", "광고", "소재", "Ad", "Asset", "Creative"),
    "keyword": ("키워드명", "키워드", "Keyword", "Criterion"),
    "level": ("변경레벨", "수준", "대상", "Change level", "Entity type", "Resource type"),
    "change_type": ("변경유형", "변경", "유형", "Change", "Change type"),
    "operation": ("변경작업", "작업", "액션", "Operation", "Action"),
    "field": ("변경필드", "항목", "변경항목", "Field", "Changed field"),
    "old_value": ("이전값", "이전 값", "변경 전", "Old value", "Before"),
    "new_value": ("변경값", "새 값", "변경 후", "New value", "After"),
    "content": ("변경내용", "변경 내용", "변경사항", "세부정보", "Details", "Change details"),
    "resource": ("원본리소스명", "리소스명", "대상명", "Resource", "Item", "Entity"),
}


META_ALIASES = {
    "account_id": ("계정ID", "계정 ID", "광고 계정 ID", "Ad account ID", "Account ID"),
    "account_name": ("계정명", "계정 이름", "광고 계정", "Ad account name", "Account name", "Account"),
    "changed_at": (
        "변경일시",
        "변경 일시",
        "일시",
        "날짜",
        "시간",
        "Activity time",
        "Activity Time",
        "Time",
        "Date",
        "Date and time",
        "Created time",
    ),
    "changed_by": ("변경자", "사용자", "작업자", "User", "Changed by", "Actor", "Person"),
    "campaign": ("캠페인명", "캠페인", "Campaign", "Campaign name", "Campaign Name"),
    "ad_group": (
        "광고세트명",
        "광고 세트명",
        "광고세트",
        "광고 세트",
        "Ad set",
        "Ad Set",
        "Ad set name",
        "Ad Set Name",
    ),
    "ad": ("소재명", "광고명", "광고", "Ad", "Ad name", "Ad Name", "Creative", "Creative name"),
    "level": ("변경레벨", "수준", "대상", "Object type", "Object Type", "Item type", "Entity type"),
    "change_type": ("변경유형", "이벤트", "활동", "Activity", "Activity type", "Event type", "Change type"),
    "operation": ("변경작업", "작업", "Action", "Operation"),
    "field": ("변경필드", "필드", "항목", "Field", "Changed field", "Property"),
    "old_value": ("이전값", "변경 전", "Old value", "Previous value", "Before"),
    "new_value": ("변경값", "변경 후", "New value", "Updated value", "After"),
    "content": ("변경내용", "변경 내용", "상세내용", "Details", "Description", "Change details"),
    "resource": ("원본리소스명", "Object ID", "Object id", "ID", "Resource"),
}


def normalize_google_records(
    source_rows: list[dict[str, Any]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
    account_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in source_rows:
        old_resource = _as_dict(row.get("old_resource"))
        new_resource = _as_dict(row.get("new_resource"))
        changed_fields = row.get("changed_fields") or []
        if isinstance(changed_fields, str):
            changed_fields = [part.strip() for part in changed_fields.split(",") if part.strip()]

        old_values = _extract_changed_values(old_resource, changed_fields)
        new_values = _extract_changed_values(new_resource, changed_fields)
        resource_type = str(row.get("change_resource_type", ""))
        operation = str(row.get("resource_change_operation", ""))
        resource_name = str(row.get("change_resource_name", ""))
        change_time = _stringify(row.get("change_date_time"))

        entity_names = _extract_google_entity_names(old_resource, new_resource)
        change_fields_text = ", ".join(changed_fields)
        change_content = _build_change_content(operation, change_fields_text, old_values, new_values)

        normalized.append(
            _base_row(
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                media="구글SA",
                account_id=account_id,
                account_name="",
                changed_at=change_time,
                changed_by=_stringify(row.get("user_email")),
                campaign=entity_names.get("campaign", ""),
                ad_group=entity_names.get("ad_group", ""),
                ad=entity_names.get("ad", ""),
                keyword=entity_names.get("keyword", ""),
                level=GOOGLE_LEVEL_MAP.get(resource_type, resource_type),
                change_type=resource_type,
                operation=operation,
                field=change_fields_text,
                old_value=_json_text(old_values),
                new_value=_json_text(new_values),
                content=change_content,
                resource=resource_name,
                raw_text=_json_text(row),
            )
        )
    return normalized


def normalize_google_browser_records(
    source_rows: list[dict[str, Any]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
    account_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in source_rows:
        content = _first(row, GOOGLE_BROWSER_ALIASES["content"])
        campaign = _first(row, GOOGLE_BROWSER_ALIASES["campaign"])
        if not campaign:
            campaign = _google_browser_name_from_content(content)
        change_type = _first(row, GOOGLE_BROWSER_ALIASES["change_type"]) or _first_line(content)
        field = _first(row, GOOGLE_BROWSER_ALIASES["field"]) or _infer_google_browser_field(content)
        normalized.append(
            _base_row(
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                media="구글SA",
                account_id=_first(row, GOOGLE_BROWSER_ALIASES["account_id"]) or account_id,
                account_name=_first(row, GOOGLE_BROWSER_ALIASES["account_name"]),
                changed_at=_first(row, GOOGLE_BROWSER_ALIASES["changed_at"]),
                changed_by=_first(row, GOOGLE_BROWSER_ALIASES["changed_by"]),
                campaign=campaign,
                ad_group=_first(row, GOOGLE_BROWSER_ALIASES["ad_group"]),
                ad=_first(row, GOOGLE_BROWSER_ALIASES["ad"]),
                keyword=_first(row, GOOGLE_BROWSER_ALIASES["keyword"]),
                level=_first(row, GOOGLE_BROWSER_ALIASES["level"]),
                change_type=change_type,
                operation=_first(row, GOOGLE_BROWSER_ALIASES["operation"]),
                field=field,
                old_value=_first(row, GOOGLE_BROWSER_ALIASES["old_value"]),
                new_value=_first(row, GOOGLE_BROWSER_ALIASES["new_value"]),
                content=content,
                resource=_first(row, GOOGLE_BROWSER_ALIASES["resource"]),
                raw_text=_json_text(row),
            )
        )
    return normalized


def normalize_meta_records(
    source_rows: list[dict[str, Any]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in source_rows:
        change_type = _first(row, META_ALIASES["change_type"])
        field = _first(row, META_ALIASES["field"]) or _infer_meta_field(row)
        old_value = _first(row, META_ALIASES["old_value"])
        new_value = _first(row, META_ALIASES["new_value"])
        content = _first(row, META_ALIASES["content"]) or _build_meta_content(
            change_type, field, old_value, new_value
        )
        normalized.append(
            _base_row(
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                media="메타",
                account_id=_first(row, META_ALIASES["account_id"]),
                account_name=_first(row, META_ALIASES["account_name"]),
                changed_at=_first(row, META_ALIASES["changed_at"]),
                changed_by=_first(row, META_ALIASES["changed_by"]),
                campaign=_first(row, META_ALIASES["campaign"]),
                ad_group=_first(row, META_ALIASES["ad_group"]),
                ad=_first(row, META_ALIASES["ad"]),
                keyword="",
                level=_normalize_meta_level(_first(row, META_ALIASES["level"])),
                change_type=change_type,
                operation=_first(row, META_ALIASES["operation"]),
                field=field,
                old_value=old_value,
                new_value=new_value,
                content=content,
                resource=_first(row, META_ALIASES["resource"]),
                raw_text=_json_text(row),
            )
        )
    return normalized


def _google_browser_name_from_content(content: str) -> str:
    for label in ("현재 이름", "이름"):
        pattern = rf"{label}\s*:\s*[\"']([^\"']+)[\"']"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()

    match = re.search(r"이름이\s+(.+?)인\s+시즌성\s+조정", content)
    if match:
        return match.group(1).strip()
    return ""


def _infer_google_browser_field(content: str) -> str:
    if "시즌성" in content or "전환율 조정" in content:
        return "시즌성 조정"
    if "예산" in content:
        return "예산"
    if "데이터 세그먼트" in content or "잠재고객" in content:
        return "데이터 세그먼트"
    if "키워드" in content:
        return "키워드"
    if "타겟 CPA" in content or "tCPA" in content:
        return "tCPA"
    return ""


def _first_line(value: str) -> str:
    return str(value or "").strip().splitlines()[0].strip() if str(value or "").strip() else ""


def normalize_naver_records(
    source_rows: list[dict[str, Any]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in source_rows:
        normalized.append(
            _base_row(
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                media="네이버SA",
                account_id=_first(row, NAVER_ALIASES["account_id"]),
                account_name=_first(row, NAVER_ALIASES["account_name"]),
                changed_at=_first(row, NAVER_ALIASES["changed_at"]),
                changed_by=_first(row, NAVER_ALIASES["changed_by"]),
                campaign=_first(row, NAVER_ALIASES["campaign"]),
                ad_group=_first(row, NAVER_ALIASES["ad_group"]),
                ad=_first(row, NAVER_ALIASES["ad"]),
                keyword=_first(row, NAVER_ALIASES["keyword"]),
                level=_first(row, NAVER_ALIASES["level"]),
                change_type=_first(row, NAVER_ALIASES["change_type"]),
                operation=_first(row, NAVER_ALIASES["operation"]),
                field=_first(row, NAVER_ALIASES["field"]),
                old_value=_first(row, NAVER_ALIASES["old_value"]),
                new_value=_first(row, NAVER_ALIASES["new_value"]),
                content=_first(row, NAVER_ALIASES["content"]),
                resource=_first(row, NAVER_ALIASES["resource"]),
                raw_text=_json_text(row),
            )
        )
    return normalized


def _infer_meta_field(row: dict[str, Any]) -> str:
    text = _json_text(row).lower()
    if any(keyword in text for keyword in ("bid strategy", "입찰전략", "bid_strategy")):
        return "입찰전략"
    if any(keyword in text for keyword in ("bid amount", "bid_amount", "입찰가")):
        return "입찰가"
    if any(keyword in text for keyword in ("status", "paused", "active", "상태", "중지", "활성")):
        return "상태"
    if any(keyword in text for keyword in ("url", "랜딩", "website")):
        return "URL"
    if any(keyword in text for keyword in ("creative", "image", "video", "소재", "이미지", "동영상")):
        return "소재"
    if any(keyword in text for keyword in ("audience", "targeting", "타겟", "잠재고객")):
        return "타겟"
    if any(keyword in text for keyword in ("budget", "예산")):
        return "예산"
    return ""


def _normalize_meta_level(value: str) -> str:
    lowered = value.lower()
    if "campaign" in lowered or "캠페인" in value:
        return "캠페인"
    if "ad set" in lowered or "adset" in lowered or "광고세트" in value or "광고 세트" in value:
        return "광고세트"
    if lowered == "ad" or lowered.startswith("ad ") or "광고" in value:
        return "소재"
    return value


def _build_meta_content(change_type: str, field: str, old_value: str, new_value: str) -> str:
    chunks = [part for part in (change_type, field) if part]
    if old_value or new_value:
        chunks.append(f"{old_value} -> {new_value}")
    return " | ".join(chunks)


def _base_row(
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
    media: str,
    account_id: str,
    account_name: str,
    changed_at: str,
    changed_by: str,
    campaign: str,
    ad_group: str,
    ad: str,
    keyword: str,
    level: str,
    change_type: str,
    operation: str,
    field: str,
    old_value: str,
    new_value: str,
    content: str,
    resource: str,
    raw_text: str,
) -> dict[str, Any]:
    date_text = _date_from_change_time(changed_at) or start_at.date().isoformat()
    return {
        "수집일시": _dt_text(collected_at),
        "조회시작일시": _dt_text(start_at),
        "조회종료일시": _dt_text(end_at),
        "일자": date_text,
        "매체": media,
        "계정ID": account_id,
        "계정명": account_name,
        "변경일시": changed_at,
        "변경자": changed_by,
        "캠페인명": campaign,
        "광고그룹명": ad_group,
        "소재명": ad,
        "키워드명": keyword,
        "변경레벨": level,
        "변경유형": change_type,
        "변경작업": operation,
        "변경필드": field,
        "이전값": old_value,
        "변경값": new_value,
        "변경내용": content,
        "원본리소스명": resource,
        "raw_text": raw_text,
        "row_hash": "",
    }


def _extract_google_entity_names(*resources: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for resource in resources:
        if not resource:
            continue
        merged.setdefault("campaign", _nested_value(resource, ("campaign", "name")))
        merged.setdefault("ad_group", _nested_value(resource, ("ad_group", "name")))
        merged.setdefault("ad", _nested_value(resource, ("ad_group_ad", "ad", "name")))
        keyword_text = _nested_value(resource, ("ad_group_criterion", "keyword", "text"))
        merged.setdefault("keyword", keyword_text)

    for key in ("campaign", "ad_group", "ad", "keyword"):
        if not merged.get(key):
            merged[key] = _deep_find_name(resources, key)
    return merged


def _extract_changed_values(resource: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in fields:
        value = _nested_value(resource, tuple(field.split(".")))
        if value != "":
            values[field] = value
    return values


def _build_change_content(
    operation: str,
    changed_fields: str,
    old_values: dict[str, Any],
    new_values: dict[str, Any],
) -> str:
    chunks = [part for part in (operation, changed_fields) if part]
    if old_values or new_values:
        chunks.append(f"{_json_text(old_values)} -> {_json_text(new_values)}")
    return " | ".join(chunks)


def _nested_value(data: dict[str, Any], path: tuple[str, ...]) -> str:
    cursor: Any = data
    for part in path:
        if not isinstance(cursor, dict):
            return ""
        cursor = cursor.get(part)
        if cursor is None:
            return ""
    return _stringify(cursor)


def _deep_find_name(resources: tuple[dict[str, Any], ...], target: str) -> str:
    candidates = {
        "campaign": ("campaign", "campaign_name"),
        "ad_group": ("ad_group", "ad_group_name"),
        "ad": ("ad", "asset", "creative"),
        "keyword": ("keyword", "text"),
    }[target]

    def walk(value: Any, parent_key: str = "") -> str:
        if isinstance(value, dict):
            if parent_key in candidates and value.get("name"):
                return _stringify(value.get("name"))
            if parent_key == "keyword" and value.get("text"):
                return _stringify(value.get("text"))
            for key, child in value.items():
                found = walk(child, key)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, parent_key)
                if found:
                    return found
        return ""

    for resource in resources:
        found = walk(resource)
        if found:
            return found
    return ""


def _first(row: dict[str, Any], names: tuple[str, ...]) -> str:
    normalized_keys = {_normalize_key(key): key for key in row.keys()}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return _stringify(row[name])
        original_key = normalized_keys.get(_normalize_key(name))
        if original_key and row.get(original_key) not in (None, ""):
            return _stringify(row[original_key])
    return ""


def _normalize_key(value: str) -> str:
    return value.replace(" ", "").replace("_", "").lower()


def _date_from_change_time(value: str) -> str:
    parsed = parse_change_datetime(value, "Asia/Seoul")
    if parsed:
        return parsed.date().isoformat()
    if not value:
        return ""
    text = value.strip()
    return text[:10] if len(text) >= 10 and text[4:5] == "-" else ""


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _json_text(value: Any) -> str:
    if value in (None, "", {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _dt_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
