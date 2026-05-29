from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import google.auth
import gspread
from gspread.exceptions import WorksheetNotFound

from utils.datetime_utils import parse_change_datetime


LOG_COLUMNS = [
    "변경일시",
    "변경일자",
    "변경자",
    "시트명",
    "행번호",
    "키워드",
    "캠페인명",
    "캠페인 ID",
    "광고그룹명",
    "광고그룹 ID",
    "키워드 ID",
    "디바이스",
    "변경필드",
    "이전값",
    "변경값",
    "raw_text",
]

AUTO_BID_CHANGE_TYPE = "자동입찰 목표순위 변경"


class AutoBidSheetChangeCollector:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger
        self._client: gspread.Client | None = None

    @property
    def client(self) -> gspread.Client:
        if self._client is None:
            credentials, _ = google.auth.default(
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ]
            )
            self._client = gspread.authorize(credentials)
        return self._client

    def collect(
        self,
        start_at: datetime,
        end_at: datetime,
        collected_at: datetime,
    ) -> list[dict[str, Any]]:
        log_start_at, log_end_at = _log_read_window(
            start_at=start_at,
            end_at=end_at,
            collected_at=collected_at,
            timezone_name=self.settings.TIMEZONE,
            lookback_days=int(getattr(self.settings, "AUTO_BID_LOG_LOOKBACK_DAYS", "7") or 7),
        )
        records = self._read_log_records()
        rows = build_auto_bid_rows_from_log_records(
            log_records=records,
            collected_at=collected_at,
            start_at=log_start_at,
            end_at=log_end_at,
            timezone_name=self.settings.TIMEZONE,
            fallback_media=self.settings.AUTO_BID_FALLBACK_MEDIA,
        )
        self.logger.info(
            "자동입찰 변경로그 조회: %s건 / Raw 후보 %s건 (%s ~ %s)",
            len(records),
            len(rows),
            _dt_text(log_start_at),
            _dt_text(log_end_at),
        )
        return rows

    def _read_log_records(self) -> list[dict[str, str]]:
        spreadsheet = self.client.open_by_key(self.settings.AUTO_BID_SPREADSHEET_ID)
        worksheet_name = getattr(self.settings, "AUTO_BID_LOG_WORKSHEET_NAME", "자동입찰_변경로그")
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except WorksheetNotFound:
            self.logger.warning("자동입찰 변경로그 탭을 찾을 수 없습니다: %s", worksheet_name)
            return []

        values = worksheet.get_all_values()
        if len(values) <= 1:
            return []

        header = [str(value).strip() for value in values[0]]
        missing = [column for column in LOG_COLUMNS if column not in header]
        if missing:
            self.logger.warning("자동입찰 변경로그 필수 컬럼 누락: %s", ", ".join(missing))

        records: list[dict[str, str]] = []
        for values_row in values[1:]:
            if not any(str(value).strip() for value in values_row):
                continue
            records.append(
                {
                    column: str(values_row[index]).strip() if len(values_row) > index else ""
                    for index, column in enumerate(header)
                }
            )
        return records


def build_auto_bid_rows_from_log_records(
    log_records: list[dict[str, Any]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
    timezone_name: str = "Asia/Seoul",
    fallback_media: str = "네이버SA",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in log_records:
        if not _record_in_window(record, start_at=start_at, end_at=end_at, timezone_name=timezone_name):
            continue
        if not _is_target_rank_field(_get(record, "변경필드")):
            continue

        keyword = _get(record, "키워드")
        old_rank = normalize_rank(_get(record, "이전값"))
        new_rank = normalize_rank(_get(record, "변경값"))
        if not keyword or not new_rank or old_rank == new_rank:
            continue

        changed_date = _record_date_text(record, timezone_name) or start_at.date().isoformat()
        changed_at = _get(record, "변경일시") or f"{changed_date} 00:00:00"
        keyword_id = _get(record, "키워드 ID")
        content = _get(record, "raw_text") or _change_content(keyword, old_rank, new_rank)

        rows.append(
            {
                "수집일시": _dt_text(collected_at),
                "조회시작일시": _dt_text(start_at),
                "조회종료일시": _dt_text(end_at),
                "일자": changed_date,
                "매체": fallback_media,
                "계정ID": "",
                "계정명": "",
                "변경일시": changed_at,
                "변경자": _get(record, "변경자"),
                "캠페인명": _get(record, "캠페인명"),
                "광고그룹명": _get(record, "광고그룹명"),
                "소재명": "",
                "키워드명": keyword,
                "변경레벨": "키워드",
                "변경유형": AUTO_BID_CHANGE_TYPE,
                "변경작업": "목표순위 변경",
                "변경필드": "목표순위",
                "이전값": old_rank,
                "변경값": new_rank,
                "변경내용": content,
                "원본리소스명": f"auto_bid_sheet_log:{keyword_id}" if keyword_id else "auto_bid_sheet_log",
                "raw_text": content,
                "_hash_source": "auto_bid_sheet",
                "_auto_bid_keyword_id": keyword_id,
                "row_hash": "",
            }
        )
    return rows


def normalize_rank(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace("순위", "").strip()


def _change_content(keyword: str, old_rank: str, new_rank: str) -> str:
    if old_rank and new_rank:
        return f"{keyword} 목표순위 {old_rank}순위 → {new_rank}순위 변경"
    return f"{keyword} 목표순위 {new_rank}순위로 신규 설정"


def _is_target_rank_field(value: Any) -> bool:
    normalized = str(value or "").replace(" ", "").strip().lower()
    return normalized == "목표순위"


def _record_in_window(
    record: dict[str, Any],
    start_at: datetime,
    end_at: datetime,
    timezone_name: str,
) -> bool:
    changed_at = parse_change_datetime(_get(record, "변경일시"), timezone_name)
    if changed_at is not None:
        return _ensure_tz(start_at, timezone_name) <= changed_at <= _ensure_tz(end_at, timezone_name)

    date_text = _get(record, "변경일자")
    if not date_text:
        return False
    try:
        changed_date = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return _ensure_tz(start_at, timezone_name).date() <= changed_date <= _ensure_tz(end_at, timezone_name).date()


def _record_date_text(record: dict[str, Any], timezone_name: str) -> str:
    changed_at = parse_change_datetime(_get(record, "변경일시"), timezone_name)
    if changed_at is not None:
        return changed_at.date().isoformat()
    date_text = _get(record, "변경일자")
    return date_text[:10] if len(date_text) >= 10 else ""


def _log_read_window(
    start_at: datetime,
    end_at: datetime,
    collected_at: datetime,
    timezone_name: str,
    lookback_days: int,
) -> tuple[datetime, datetime]:
    if lookback_days <= 1:
        return start_at, end_at

    tz = ZoneInfo(timezone_name)
    local_start = _ensure_tz(start_at, timezone_name)
    local_end = _ensure_tz(end_at, timezone_name)
    local_collected = _ensure_tz(collected_at, timezone_name)
    if local_start.date() != local_collected.date() or local_end.date() != local_collected.date():
        return local_start, local_end

    start_date = local_collected.date() - timedelta(days=lookback_days - 1)
    return datetime.combine(start_date, time.min, tzinfo=tz), local_end


def _ensure_tz(value: datetime, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)


def _get(record: dict[str, Any], key: str) -> str:
    return str(record.get(key, "") or "").strip()


def _dt_text(value: datetime) -> str:
    return _ensure_tz(value, "Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S")
