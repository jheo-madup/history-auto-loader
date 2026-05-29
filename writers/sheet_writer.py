from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import gspread
import google.auth
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from gspread.utils import rowcol_to_a1

from processors.normalizer import RAW_COLUMNS
from utils.datetime_utils import parse_change_datetime


class SheetWriterError(RuntimeError):
    pass


RAW_ATTENTION_FORMAT = {
    "backgroundColor": {
        "red": 1.0,
        "green": 0.9568627451,
        "blue": 0.6588235294,
    }
}


class SheetWriter:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger
        self._client: gspread.Client | None = None
        self._spreadsheet: gspread.Spreadsheet | None = None

    @property
    def client(self) -> gspread.Client:
        if self._client is None:
            try:
                credentials, _ = google.auth.default(
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive",
                    ]
                )
                self._client = gspread.authorize(credentials)
            except Exception as exc:  # noqa: BLE001
                raise SheetWriterError(
                    "Google Sheets 인증 실패: Cloud Run Job 서비스 계정에 시트 접근 권한이 있는지 확인하세요."
                ) from exc
        return self._client

    @property
    def spreadsheet(self) -> gspread.Spreadsheet:
        if self._spreadsheet is None:
            try:
                self._spreadsheet = self.client.open_by_key(self.settings.SPREADSHEET_ID)
            except SpreadsheetNotFound as exc:
                raise SheetWriterError(
                    f"Spreadsheet 접근 실패: {self.settings.SPREADSHEET_ID}. 서비스 계정 공유 권한을 확인하세요."
                ) from exc
            except APIError as exc:
                raise SheetWriterError(f"Spreadsheet API 오류: {exc}") from exc
        return self._spreadsheet

    def get_existing_row_hashes(self) -> set[str]:
        worksheet = self._worksheet(self.settings.RAW_WORKSHEET_NAME)
        self._ensure_raw_header(worksheet)
        values = worksheet.get_all_values()
        if not values:
            return set()
        header = values[0]
        try:
            hash_index = header.index("row_hash")
        except ValueError as exc:
            raise SheetWriterError("Raw 탭에 row_hash 컬럼이 없습니다.") from exc
        return {row[hash_index].strip() for row in values[1:] if len(row) > hash_index and row[hash_index].strip()}

    def append_raw_rows(self, rows: list[dict[str, Any]]) -> None:
        worksheet = self._worksheet(self.settings.RAW_WORKSHEET_NAME)
        self._ensure_raw_header(worksheet)
        if not rows:
            self.logger.info("Raw 신규 append 대상이 없습니다.")
            return
        values = [[row.get(column, "") for column in RAW_COLUMNS] for row in rows]
        try:
            start_row = len(worksheet.get_all_values()) + 1
            worksheet.append_rows(values, value_input_option="USER_ENTERED")
            self._format_attention_raw_rows(worksheet, rows, start_row=start_row)
        except APIError as exc:
            raise SheetWriterError(f"Raw append 실패: {exc}") from exc

    def merge_recent_raw_rows(
        self,
        rows: list[dict[str, Any]],
        collected_at: datetime,
        timezone_name: str,
        days: int = 7,
    ) -> dict[str, Any]:
        worksheet = self._worksheet(self.settings.RAW_WORKSHEET_NAME)
        self._ensure_raw_header(worksheet)
        try:
            existing_records = worksheet.get_all_records(expected_headers=RAW_COLUMNS)
            recent_existing = filter_recent_raw_records(
                existing_records,
                collected_at=collected_at,
                timezone_name=timezone_name,
                days=days,
            )
            existing_hashes = {
                str(record.get("row_hash", "")).strip()
                for record in recent_existing
                if str(record.get("row_hash", "")).strip()
            }
            existing_semantic_keys = {_raw_dedupe_key(_raw_record(record)) for record in recent_existing}
            incoming_rows = [
                _raw_record(row)
                for row in rows
                if str(row.get("row_hash", "")).strip()
            ]
            new_candidates = [
                row
                for row in incoming_rows
                if str(row.get("row_hash", "")).strip() not in existing_hashes
                and _raw_dedupe_key(row) not in existing_semantic_keys
            ]
            new_rows = dedupe_raw_records(new_candidates)
            merged_rows = dedupe_raw_records(
                [_raw_record(record) for record in recent_existing] + incoming_rows
            )
            values = [RAW_COLUMNS] + [
                [row.get(column, "") for column in RAW_COLUMNS] for row in merged_rows
            ]
            worksheet.clear()
            worksheet.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
            self._format_attention_raw_rows(worksheet, merged_rows, start_row=2)
            return {
                "new": len(new_rows),
                "input": len(rows),
                "duplicates": len(rows) - len(new_rows),
                "retained_existing": len(recent_existing),
                "pruned": len(existing_records) - len(recent_existing),
                "final": len(merged_rows),
                "new_by_media": _count_by_media(new_rows),
            }
        except APIError as exc:
            raise SheetWriterError(f"Raw 최근 7일 merge 실패: {exc}") from exc

    def highlight_attention_raw_rows(self, date_text: str | None = None) -> int:
        worksheet = self._worksheet(self.settings.RAW_WORKSHEET_NAME)
        self._ensure_raw_header(worksheet)
        try:
            values = worksheet.get_all_values()
            if not values:
                return 0
            header = values[0]
            rows: list[dict[str, Any]] = []
            sheet_rows: list[int] = []
            for sheet_row, values_row in enumerate(values[1:], start=2):
                row = {
                    column: values_row[index] if len(values_row) > index else ""
                    for index, column in enumerate(header)
                }
                if date_text and str(row.get("일자", "")).strip() != date_text:
                    continue
                if _needs_raw_attention(row):
                    rows.append(row)
                    sheet_rows.append(sheet_row)
            self._format_raw_row_numbers(worksheet, sheet_rows)
            return len(rows)
        except APIError as exc:
            raise SheetWriterError(f"Raw 주의 행 색상 적용 실패: {exc}") from exc

    def get_raw_records_for(self, date_text: str, media: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.get_raw_records_for_date(date_text=date_text)
            if str(record.get("매체", "")).strip() == media
        ]

    def get_raw_records_for_date(self, date_text: str) -> list[dict[str, Any]]:
        worksheet = self._worksheet(self.settings.RAW_WORKSHEET_NAME)
        self._ensure_raw_header(worksheet)
        try:
            records = worksheet.get_all_records(expected_headers=RAW_COLUMNS)
        except APIError as exc:
            raise SheetWriterError(f"Raw 조회 실패: {exc}") from exc
        return [
            record
            for record in records
            if str(record.get("일자", "")).strip() == date_text
        ]

    def update_summary_cell(self, date_text: str, media: str, summary_text: str) -> None:
        worksheet = self._worksheet(self.settings.SUMMARY_WORKSHEET_NAME)
        media_col = self._summary_media_col(worksheet, media)
        row_index = self._summary_date_row(worksheet, date_text)
        try:
            worksheet.update_cell(row_index, media_col, summary_text)
        except APIError as exc:
            raise SheetWriterError(f"Summary 셀 업데이트 실패: {exc}") from exc

    def ensure_summary_media_columns(self, media_names: list[str]) -> None:
        worksheet = self._worksheet(self.settings.SUMMARY_WORKSHEET_NAME)
        try:
            header = [str(value).strip() for value in worksheet.row_values(2)]
            next_col = max(len(header) + 1, 2)
            for media in media_names:
                if media in header:
                    continue
                if next_col > worksheet.col_count:
                    worksheet.add_cols(next_col - worksheet.col_count)
                worksheet.update_cell(2, next_col, media)
                header.append(media)
                self.logger.info("Summary 매체 컬럼 추가: %s", media)
                next_col += 1
        except APIError as exc:
            raise SheetWriterError(f"Summary 매체 컬럼 추가 실패: {exc}") from exc

    def _worksheet(self, name: str) -> gspread.Worksheet:
        try:
            return self.spreadsheet.worksheet(name)
        except WorksheetNotFound as exc:
            raise SheetWriterError(f"워크시트를 찾을 수 없습니다: {name}") from exc
        except APIError as exc:
            raise SheetWriterError(f"워크시트 접근 실패({name}): {exc}") from exc

    def _ensure_raw_header(self, worksheet: gspread.Worksheet) -> None:
        try:
            first_row = worksheet.row_values(1)
            if first_row == RAW_COLUMNS:
                return
            if not first_row:
                worksheet.update(
                    values=[RAW_COLUMNS],
                    range_name="A1",
                    value_input_option="USER_ENTERED",
                )
                return
            missing = [column for column in RAW_COLUMNS if column not in first_row]
            if missing:
                values = worksheet.get_all_values()
                has_existing_data = any(
                    any(str(cell).strip() for cell in row) for row in values[1:]
                )
                if not has_existing_data:
                    self.logger.warning(
                        "Raw 탭에 기존 데이터가 없어 헤더를 새 스키마로 초기화합니다."
                    )
                    worksheet.update(
                        values=[RAW_COLUMNS],
                        range_name="A1",
                        value_input_option="USER_ENTERED",
                    )
                    return
                raise SheetWriterError(f"Raw 탭 헤더가 예상과 다릅니다. 누락 컬럼: {missing}")
        except APIError as exc:
            raise SheetWriterError(f"Raw 헤더 확인 실패: {exc}") from exc

    def _format_attention_raw_rows(
        self,
        worksheet: gspread.Worksheet,
        rows: list[dict[str, Any]],
        start_row: int,
    ) -> None:
        sheet_rows = [
            start_row + offset for offset, row in enumerate(rows) if _needs_raw_attention(row)
        ]
        try:
            self._format_raw_row_numbers(worksheet, sheet_rows)
        except APIError as exc:
            self.logger.warning("Raw 주의 행 색상 적용 실패: %s", exc)

    @staticmethod
    def _format_raw_row_numbers(worksheet: gspread.Worksheet, sheet_rows: list[int]) -> None:
        for start, end in _contiguous_ranges(sheet_rows):
            range_name = f"{rowcol_to_a1(start, 1)}:{rowcol_to_a1(end, len(RAW_COLUMNS))}"
            worksheet.format(range_name, RAW_ATTENTION_FORMAT)

    def _summary_media_col(self, worksheet: gspread.Worksheet, media: str) -> int:
        try:
            header = worksheet.row_values(2)
        except APIError as exc:
            raise SheetWriterError(f"Summary 2행 매체 헤더 조회 실패: {exc}") from exc

        try:
            normalized = [str(value).strip() for value in header]
            return normalized.index(media) + 1
        except ValueError as exc:
            raise SheetWriterError(
                f"Summary 탭 2행에 매체 컬럼이 없습니다: {media}."
            ) from exc

    def _summary_date_row(self, worksheet: gspread.Worksheet, date_text: str) -> int:
        try:
            date_values = worksheet.col_values(1)
        except APIError as exc:
            raise SheetWriterError(f"Summary A열 일자 조회 실패: {exc}") from exc

        for index, value in enumerate(date_values, start=1):
            if str(value).strip() == date_text:
                return index

        next_row = max(len(date_values) + 1, 3)
        try:
            worksheet.update_cell(next_row, 1, date_text)
        except APIError as exc:
            raise SheetWriterError(f"Summary 일자 행 추가 실패: {exc}") from exc
        return next_row


def _needs_raw_attention(row: dict[str, Any]) -> bool:
    media = str(row.get("매체", "")).strip()
    if not media.startswith("네이버"):
        return False

    entity_columns = ("캠페인명", "광고그룹명", "소재명", "키워드명")
    has_entity = any(str(row.get(column, "")).strip() for column in entity_columns)
    if not has_entity:
        return True

    text = " ".join(
        str(row.get(column, ""))
        for column in (
            "변경유형",
            "변경작업",
            "변경필드",
            "변경내용",
            "raw_text",
        )
    )
    return any(keyword in text for keyword in ("소재 검수", "키워드 검토", "검토 상태", "검수", "심사"))


def filter_recent_raw_records(
    records: list[dict[str, Any]],
    collected_at: datetime,
    timezone_name: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    if collected_at.tzinfo is None:
        local_now = collected_at.replace(tzinfo=tz)
    else:
        local_now = collected_at.astimezone(tz)
    start_date = local_now.date() - timedelta(days=days - 1)
    end_date = local_now.date()
    return [
        record
        for record in records
        if _record_date(record, timezone_name) is not None
        and start_date <= _record_date(record, timezone_name) <= end_date
    ]


def _record_date(record: dict[str, Any], timezone_name: str):
    changed_at = parse_change_datetime(str(record.get("변경일시", "")), timezone_name)
    if changed_at is not None:
        return changed_at.date()
    date_text = str(record.get("일자", "")).strip()
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _raw_record(row: dict[str, Any]) -> dict[str, Any]:
    return {column: row.get(column, "") for column in RAW_COLUMNS}


def dedupe_raw_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
    scores: dict[tuple[str, ...], tuple[int, int]] = {}
    for index, record in enumerate(records):
        key = _raw_dedupe_key(record)
        score = (_media_specificity(record), index)
        if key not in deduped or score >= scores[key]:
            deduped[key] = record
            scores[key] = score
    return list(deduped.values())


def _raw_dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    fields = (
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
    )
    return tuple(str(row.get(field, "") or "").strip().replace("\r\n", "\n") for field in fields)


def _media_specificity(row: dict[str, Any]) -> int:
    media = str(row.get("매체", "")).strip()
    return 0 if media in {"", "네이버SA", "구글SA", "구글AC"} else 10


def _count_by_media(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        media = str(row.get("매체", "") or "").strip()
        if not media:
            continue
        counts[media] = counts.get(media, 0) + 1
    return counts


def _contiguous_ranges(numbers: list[int]) -> list[tuple[int, int]]:
    if not numbers:
        return []

    ranges: list[tuple[int, int]] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))
    return ranges
