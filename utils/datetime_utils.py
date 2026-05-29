from __future__ import annotations

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo


DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")
CHANGE_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d. %H:%M:%S",
    "%Y.%m.%d. %H:%M",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d.",
    "%Y.%m.%d",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%Y-%m-%d %I:%M:%S %p",
    "%Y-%m-%d %I:%M %p",
)


def get_collection_window(
    timezone_name: str,
    date_text: str | None = None,
    start_text: str | None = None,
    end_text: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)

    if start_text or end_text:
        if not start_text or not end_text:
            raise ValueError("--start와 --end는 함께 입력해야 합니다.")
        start_at = parse_local_datetime(start_text, tz)
        end_at = parse_local_datetime(end_text, tz)
        return start_at, end_at, now

    if date_text:
        target_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        start_at = datetime.combine(target_date, time.min, tzinfo=tz)
        if target_date == now.date():
            end_at = now
        else:
            end_at = datetime.combine(target_date, time.max.replace(microsecond=0), tzinfo=tz)
        return start_at, end_at, now

    start_at = datetime.combine(now.date(), time.min, tzinfo=tz)
    end_at = now
    return start_at, end_at, now


def parse_local_datetime(value: str, tz: ZoneInfo) -> datetime:
    for fmt in DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"지원하지 않는 일시 형식입니다: {value}")


def parse_change_datetime(value: str, timezone_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    tz = ZoneInfo(timezone_name)
    normalized = _normalize_korean_datetime(text)
    for fmt in CHANGE_DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=tz)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
    except ValueError:
        return None


def row_in_collection_window(row: dict[str, object], start_at: datetime, end_at: datetime, timezone_name: str) -> bool:
    changed_at = parse_change_datetime(str(row.get("변경일시", "")), timezone_name)
    if changed_at is None:
        return False
    return start_at <= changed_at <= end_at


def filter_rows_by_collection_window(
    rows: list[dict[str, object]],
    start_at: datetime,
    end_at: datetime,
    timezone_name: str,
) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row_in_collection_window(row, start_at=start_at, end_at=end_at, timezone_name=timezone_name)
    ]


def _normalize_korean_datetime(value: str) -> str:
    text = value.replace("KST", "").strip()
    match = re.search(
        r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(오전|오후)\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?",
        text,
    )
    if match:
        year, month, day, meridiem, hour, minute, second = match.groups()
        hour_int = _to_24_hour(int(hour), meridiem)
        return (
            f"{year}.{int(month):02d}.{int(day):02d}. "
            f"{hour_int:02d}:{int(minute):02d}:{int(second or 0):02d}"
        )

    match = re.search(
        r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(오전|오후)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?(?:\s*(\d{1,2})초)?",
        text,
    )
    if not match:
        return text

    year, month, day, meridiem, hour, minute, second = match.groups()
    hour_int = _to_24_hour(int(hour), meridiem)
    return (
        f"{year}.{int(month):02d}.{int(day):02d}. "
        f"{hour_int:02d}:{int(minute or 0):02d}:{int(second or 0):02d}"
    )


def _to_24_hour(hour: int, meridiem: str) -> int:
    hour_int = hour
    if meridiem == "오후" and hour_int < 12:
        hour_int += 12
    if meridiem == "오전" and hour_int == 12:
        hour_int = 0
    return hour_int
