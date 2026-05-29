from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import google.auth
import gspread
from gspread.exceptions import APIError, WorksheetNotFound


STATE_COLUMNS = [
    "keyword",
    "target_rank",
    "campaign",
    "ad_group",
    "media",
    "raw_text",
    "updated_at",
]


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
        current_records = self._read_current_records()
        previous_snapshot = self._read_snapshot()
        rows = build_auto_bid_change_rows(
            current_records=current_records,
            previous_snapshot=previous_snapshot,
            collected_at=collected_at,
            start_at=start_at,
            end_at=end_at,
            fallback_media=self.settings.AUTO_BID_FALLBACK_MEDIA,
        )
        self._write_snapshot(current_records=current_records, collected_at=collected_at)
        if not previous_snapshot:
            self.logger.info("자동입찰시트 최초 스냅샷 저장: %s건", len(current_records))
            return []
        self.logger.info("자동입찰시트 목표순위 변경 감지: %s건", len(rows))
        return rows

    def _read_current_records(self) -> list[dict[str, str]]:
        spreadsheet = self.client.open_by_key(self.settings.AUTO_BID_SPREADSHEET_ID)
        worksheet = _worksheet_by_name_or_gid(
            spreadsheet=spreadsheet,
            worksheet_name=self.settings.AUTO_BID_WORKSHEET_NAME,
            worksheet_gid=self.settings.AUTO_BID_WORKSHEET_GID,
        )
        values = worksheet.get_all_values()
        header_row = max(1, int(self.settings.AUTO_BID_HEADER_ROW))
        if len(values) < header_row:
            return []

        header = [str(value).strip() for value in values[header_row - 1]]
        keyword_index = _required_column(
            header,
            self.settings.AUTO_BID_KEYWORD_COLUMN,
            aliases=("키워드", "keyword", "Keyword"),
        )
        rank_index = _required_column(
            header,
            self.settings.AUTO_BID_TARGET_RANK_COLUMN,
            aliases=("목표순위", "목표 순위", "target_rank", "Target Rank"),
        )
        campaign_index = _optional_column(
            header,
            self.settings.AUTO_BID_CAMPAIGN_COLUMN,
            aliases=("캠페인명", "캠페인", "Campaign", "campaign"),
        )
        ad_group_index = _optional_column(
            header,
            self.settings.AUTO_BID_AD_GROUP_COLUMN,
            aliases=("광고그룹명", "광고그룹", "Ad Group", "ad_group"),
        )
        media_index = _optional_column(
            header,
            self.settings.AUTO_BID_MEDIA_COLUMN,
            aliases=("매체", "Media", "media"),
        )

        records: list[dict[str, str]] = []
        for row in values[header_row:]:
            keyword = _cell(row, keyword_index)
            if not keyword:
                continue
            record = {
                "keyword": keyword,
                "target_rank": normalize_rank(_cell(row, rank_index)),
                "campaign": _cell(row, campaign_index) if campaign_index is not None else "",
                "ad_group": _cell(row, ad_group_index) if ad_group_index is not None else "",
                "media": _cell(row, media_index) if media_index is not None else "",
                "raw_text": _row_text(header, row),
            }
            records.append(record)
        return records

    def _state_worksheet(self) -> gspread.Worksheet:
        spreadsheet = self.client.open_by_key(self.settings.SPREADSHEET_ID)
        name = self.settings.AUTO_BID_STATE_WORKSHEET_NAME
        try:
            worksheet = spreadsheet.worksheet(name)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(STATE_COLUMNS))
            try:
                spreadsheet.batch_update(
                    {
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {"sheetId": worksheet.id, "hidden": True},
                                    "fields": "hidden",
                                }
                            }
                        ]
                    }
                )
            except APIError as exc:
                self.logger.warning("자동입찰 스냅샷 탭 숨김 처리 실패: %s", exc)
        _ensure_state_header(worksheet)
        return worksheet

    def _read_snapshot(self) -> dict[str, dict[str, str]]:
        worksheet = self._state_worksheet()
        values = worksheet.get_all_values()
        if len(values) <= 1:
            return {}
        header = values[0]
        snapshot: dict[str, dict[str, str]] = {}
        for row in values[1:]:
            record = {
                column: row[index] if len(row) > index else ""
                for index, column in enumerate(header)
            }
            keyword = record.get("keyword", "").strip()
            if keyword:
                snapshot[_snapshot_key(keyword)] = record
        return snapshot

    def _write_snapshot(
        self,
        current_records: list[dict[str, str]],
        collected_at: datetime,
    ) -> None:
        worksheet = self._state_worksheet()
        updated_at = _dt_text(collected_at)
        values = [STATE_COLUMNS]
        for record in current_records:
            values.append(
                [
                    record.get("keyword", ""),
                    record.get("target_rank", ""),
                    record.get("campaign", ""),
                    record.get("ad_group", ""),
                    record.get("media", ""),
                    record.get("raw_text", ""),
                    updated_at,
                ]
            )
        worksheet.clear()
        worksheet.update(values=values, range_name="A1", value_input_option="USER_ENTERED")


def build_auto_bid_change_rows(
    current_records: list[dict[str, str]],
    previous_snapshot: dict[str, dict[str, str]],
    collected_at: datetime,
    start_at: datetime,
    end_at: datetime,
    fallback_media: str = "네이버SA",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not previous_snapshot:
        return rows

    run_date = collected_at.date().isoformat()
    for record in current_records:
        keyword = record.get("keyword", "").strip()
        if not keyword:
            continue
        previous = previous_snapshot.get(_snapshot_key(keyword))
        old_rank = normalize_rank(previous.get("target_rank", "")) if previous else ""
        new_rank = normalize_rank(record.get("target_rank", ""))
        if old_rank == new_rank:
            continue
        if not old_rank and not new_rank:
            continue
        raw_text = (
            "source=bid_sheet"
            f"|keyword={keyword}"
            f"|old_rank={old_rank}"
            f"|new_rank={new_rank}"
            f"|date={run_date}"
        )
        rows.append(
            {
                "수집일시": _dt_text(collected_at),
                "조회시작일시": _dt_text(start_at),
                "조회종료일시": _dt_text(end_at),
                "일자": run_date,
                "매체": record.get("media", "").strip() or fallback_media,
                "계정ID": "",
                "계정명": "",
                "변경일시": _dt_text(collected_at),
                "변경자": "",
                "캠페인명": record.get("campaign", ""),
                "광고그룹명": record.get("ad_group", ""),
                "소재명": "",
                "키워드명": keyword,
                "변경레벨": "키워드",
                "변경유형": "자동입찰 목표순위 변경",
                "변경작업": "수정",
                "변경필드": "목표순위",
                "이전값": old_rank,
                "변경값": new_rank,
                "변경내용": _change_content(keyword, old_rank, new_rank),
                "원본리소스명": "auto_bid_sheet",
                "raw_text": raw_text,
                "_hash_source": "bid_sheet",
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
    if new_rank:
        return f"{keyword} 목표순위 {new_rank}순위로 변경"
    return f"{keyword} 목표순위 변경"


def _worksheet_by_name_or_gid(
    spreadsheet: gspread.Spreadsheet,
    worksheet_name: str,
    worksheet_gid: str,
) -> gspread.Worksheet:
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    gid = int(worksheet_gid)
    worksheet = spreadsheet.get_worksheet_by_id(gid)
    if worksheet is None:
        raise WorksheetNotFound(f"워크시트 gid를 찾을 수 없습니다: {gid}")
    return worksheet


def _ensure_state_header(worksheet: gspread.Worksheet) -> None:
    header = worksheet.row_values(1)
    if header == STATE_COLUMNS:
        return
    worksheet.update(values=[STATE_COLUMNS], range_name="A1", value_input_option="USER_ENTERED")


def _required_column(header: list[str], column_name: str, aliases: tuple[str, ...] = ()) -> int:
    index = _find_column(header, (column_name, *aliases))
    if index is None:
        expected = ", ".join(value for value in (column_name, *aliases) if value)
        raise ValueError(f"자동입찰시트 필수 컬럼이 없습니다: {expected}") from None
    return index


def _optional_column(header: list[str], column_name: str, aliases: tuple[str, ...] = ()) -> int | None:
    return _find_column(header, (column_name, *aliases))


def _find_column(header: list[str], names: tuple[str, ...]) -> int | None:
    normalized_header = [_normalize_column_name(value) for value in header]
    for name in names:
        normalized_name = _normalize_column_name(name)
        if not normalized_name:
            continue
        try:
            return normalized_header.index(normalized_name)
        except ValueError:
            continue
    return None


def _normalize_column_name(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").strip().lower())


def _cell(row: list[str], index: int) -> str:
    return str(row[index]).strip() if len(row) > index else ""


def _row_text(header: list[str], row: list[str]) -> str:
    pairs = []
    for index, column in enumerate(header):
        value = _cell(row, index)
        if value:
            pairs.append(f"{column}={value}")
    return " | ".join(pairs)


def _snapshot_key(keyword: str) -> str:
    return " ".join(str(keyword or "").strip().lower().split())


def _dt_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
