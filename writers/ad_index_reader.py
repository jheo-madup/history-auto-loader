from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import google.auth
import gspread
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound


MEDIA_ALIASES = {
    "네이버SA_파워콘텐츠": "네이버 파워컨텐츠",
    "네이버SA_파워컨텐츠": "네이버 파워컨텐츠",
    "네이버 파워콘텐츠": "네이버 파워컨텐츠",
    "네이버 브랜드검색": "BS - 네이버",
    "브랜드검색": "BS - 네이버",
    "네이버BS": "BS - 네이버",
}


class AdIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class CampaignMediaIndex:
    campaign_to_media: dict[str, str]
    ad_group_to_media: dict[str, str]
    campaign_to_summary_entity: dict[str, str]
    ad_group_to_summary_entity: dict[str, str]
    summary_entity_media: str

    def route_rows(self, rows: list[dict[str, Any]], logger: Any | None = None) -> list[dict[str, Any]]:
        routed: list[dict[str, Any]] = []
        for row in rows:
            campaign = str(row.get("캠페인명", "")).strip()
            ad_group = str(row.get("광고그룹명", "")).strip()
            media = self.lookup(campaign=campaign, ad_group=ad_group)
            if media:
                updated = dict(row)
                updated["매체"] = media
                routed.append(updated)
            else:
                if logger:
                    logger.warning(
                        "인덱스 매칭 실패: campaign=%s, ad_group=%s, fallback_media=%s",
                        campaign,
                        ad_group,
                        row.get("매체", ""),
                    )
                routed.append(row)
        return routed

    def enrich_summary_rows(self, rows: list[dict[str, Any]], media: str) -> list[dict[str, Any]]:
        if media != self.summary_entity_media:
            return rows

        enriched: list[dict[str, Any]] = []
        for row in rows:
            campaign = str(row.get("캠페인명", "")).strip()
            ad_group = str(row.get("광고그룹명", "")).strip()
            summary_entity = self.summary_entity_for(campaign=campaign, ad_group=ad_group)
            if summary_entity:
                updated = dict(row)
                updated["_summary_entity_override"] = summary_entity
                enriched.append(updated)
            else:
                enriched.append(row)
        return enriched

    def lookup(self, campaign: str, ad_group: str = "") -> str:
        media = self.campaign_to_media.get(_normalize_campaign(campaign), "")
        if media:
            return media
        for key in _normalize_ad_group_keys(ad_group):
            media = self.ad_group_to_media.get(key)
            if media:
                return media
        return _infer_media_from_names(campaign=campaign, ad_group=ad_group)

    def summary_entity_for(self, campaign: str, ad_group: str = "") -> str:
        summary_entity = self.campaign_to_summary_entity.get(_normalize_campaign(campaign), "")
        if summary_entity:
            return summary_entity
        for key in _normalize_ad_group_keys(ad_group):
            summary_entity = self.ad_group_to_summary_entity.get(key)
            if summary_entity:
                return summary_entity
        return ""


def load_campaign_media_index(settings: Any, logger: Any) -> CampaignMediaIndex | None:
    if not settings.AD_INDEX_ENABLED:
        return None
    if not settings.AD_INDEX_SPREADSHEET_ID:
        return None

    try:
        values = _read_index_values(settings)
        index = _build_index(settings=settings, values=values, logger=logger)
    except AdIndexError:
        raise
    except Exception as exc:  # noqa: BLE001 - caller logs and falls back.
        raise AdIndexError(f"광고 인덱스 조회 실패: {exc}") from exc

    logger.info(
        "광고 인덱스 매체 매핑 로드: %s개 캠페인 / 요약 분류 %s개",
        len(index.campaign_to_media) + len(index.ad_group_to_media),
        len(index.campaign_to_summary_entity) + len(index.ad_group_to_summary_entity),
    )
    return index


def _read_index_values(settings: Any) -> list[list[str]]:
    credentials, _ = google.auth.default(
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    client = gspread.authorize(credentials)

    try:
        spreadsheet = client.open_by_key(settings.AD_INDEX_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(settings.AD_INDEX_WORKSHEET_NAME)
        return worksheet.get_all_values()
    except SpreadsheetNotFound as exc:
        raise AdIndexError(
            f"광고 인덱스 Spreadsheet 접근 실패: {settings.AD_INDEX_SPREADSHEET_ID}"
        ) from exc
    except WorksheetNotFound as exc:
        raise AdIndexError(
            f"광고 인덱스 탭을 찾을 수 없습니다: {settings.AD_INDEX_WORKSHEET_NAME}"
        ) from exc
    except APIError as exc:
        raise AdIndexError(f"광고 인덱스 API 오류: {exc}") from exc


def _build_index(settings: Any, values: list[list[str]], logger: Any) -> CampaignMediaIndex:
    header_row = _header_row(settings.AD_INDEX_HEADER_ROW)
    if len(values) < header_row:
        raise AdIndexError(f"광고 인덱스 헤더 행이 없습니다: {header_row}")

    header = [str(value).strip() for value in values[header_row - 1]]
    campaign_index = _required_column(header, settings.AD_INDEX_CAMPAIGN_COLUMN)
    ad_group_index = _optional_column(header, settings.AD_INDEX_AD_GROUP_COLUMN)
    media_index = _required_column(header, settings.AD_INDEX_MEDIA_COLUMN)
    summary_index = _optional_column(header, settings.AD_INDEX_SUMMARY_COLUMN)
    if campaign_index is None or media_index is None:
        raise AdIndexError(
            "광고 인덱스 필수 컬럼이 없습니다: "
            f"{settings.AD_INDEX_CAMPAIGN_COLUMN}, {settings.AD_INDEX_MEDIA_COLUMN}"
        )

    media_votes: dict[str, Counter[str]] = defaultdict(Counter)
    group_media_votes: dict[str, Counter[str]] = defaultdict(Counter)
    summary_votes: dict[str, Counter[str]] = defaultdict(Counter)
    group_summary_votes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in values[header_row:]:
        campaign = _cell(row, campaign_index)
        ad_group = _cell(row, ad_group_index) if ad_group_index is not None else ""
        media = _normalize_media(_cell(row, media_index))
        if not media or media == "#N/A" or (not campaign and not ad_group):
            continue
        if campaign:
            normalized_campaign = _normalize_campaign(campaign)
            media_votes[normalized_campaign][media] += 1
        for group_key in _normalize_ad_group_keys(ad_group):
            group_media_votes[group_key][media] += 1

        if summary_index is not None:
            summary_entity = _normalize_summary_entity(_cell(row, summary_index))
            if summary_entity:
                if campaign:
                    summary_votes[_normalize_campaign(campaign)][summary_entity] += 1
                for group_key in _normalize_ad_group_keys(ad_group):
                    group_summary_votes[group_key][summary_entity] += 1

    campaign_to_media: dict[str, str] = {}
    ad_group_to_media: dict[str, str] = {}
    campaign_to_summary_entity: dict[str, str] = {}
    ad_group_to_summary_entity: dict[str, str] = {}
    conflict_count = 0
    for campaign, counter in media_votes.items():
        if len(counter) > 1:
            conflict_count += 1
        campaign_to_media[campaign] = counter.most_common(1)[0][0]
    for ad_group, counter in group_media_votes.items():
        if len(counter) > 1:
            conflict_count += 1
        ad_group_to_media[ad_group] = counter.most_common(1)[0][0]
    for campaign, counter in summary_votes.items():
        campaign_to_summary_entity[campaign] = counter.most_common(1)[0][0]
    for ad_group, counter in group_summary_votes.items():
        ad_group_to_summary_entity[ad_group] = counter.most_common(1)[0][0]

    if conflict_count:
        logger.warning("광고 인덱스에서 매체가 중복된 캠페인 %s개는 최빈값을 사용합니다.", conflict_count)

    return CampaignMediaIndex(
        campaign_to_media=campaign_to_media,
        ad_group_to_media=ad_group_to_media,
        campaign_to_summary_entity=campaign_to_summary_entity,
        ad_group_to_summary_entity=ad_group_to_summary_entity,
        summary_entity_media=settings.AD_INDEX_SUMMARY_ENTITY_MEDIA,
    )


def _required_column(header: list[str], column_name: str) -> int | None:
    try:
        return header.index(column_name)
    except ValueError:
        return None


def _optional_column(header: list[str], column_name: str) -> int | None:
    if not column_name:
        return None
    return _required_column(header, column_name)


def _header_row(value: str) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 5


def _cell(row: list[str], index: int) -> str:
    return str(row[index]).strip() if len(row) > index else ""


def _normalize_campaign(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_ad_group_keys(value: str) -> tuple[str, ...]:
    normalized = " ".join(str(value or "").strip().lower().split())
    if not normalized or normalized == "#n/a":
        return ()

    keys = {normalized}
    for suffix in ("_g",):
        if normalized.endswith(suffix):
            keys.add(normalized[: -len(suffix)])
    return tuple(key for key in keys if key)


def _normalize_media(value: str) -> str:
    media = str(value or "").strip()
    return MEDIA_ALIASES.get(media, media)


def _infer_media_from_names(campaign: str, ad_group: str) -> str:
    campaign_text = str(campaign or "").strip().lower()
    ad_group_text = str(ad_group or "").strip().lower()
    if "브랜드검색" in campaign_text or "brand search" in campaign_text:
        return "BS - 네이버"
    if re.match(r"^\d{4}_", ad_group_text) and any(
        marker in ad_group_text
        for marker in ("ml-listing", "pl-normal", "pp-image", "brand", "브랜드")
    ):
        return "BS - 네이버"
    return ""


def _normalize_summary_entity(value: str) -> str:
    text = str(value or "").strip()
    return "" if not text or text == "#N/A" else text
