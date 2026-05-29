from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

from collectors.auto_bid_sheet_change import AutoBidSheetChangeCollector
from collectors.google_ads_browser_change import GoogleAdsBrowserChangeCollector
from collectors.google_ads_change import GoogleAdsChangeCollector
from collectors.meta_change import MetaChangeCollector
from collectors.naver_sa_change import NaverSAChangeCollector
from config import settings
from notifiers.slack_notifier import SlackNotifier, count_rows_by_media
from processors.filters import apply_raw_filters
from processors.google_media_router import route_google_media
from processors.normalizer import (
    normalize_google_browser_records,
    normalize_google_records,
    normalize_meta_records,
    normalize_naver_records,
)
from processors.summarizer import build_summary
from utils.datetime_utils import filter_rows_by_collection_window, get_collection_window
from utils.hash_utils import attach_row_hash
from utils.logger import get_logger
from writers.ad_index_reader import CampaignMediaIndex, load_campaign_media_index
from writers.sheet_writer import SheetWriter, SheetWriterError


LOGGER = get_logger("sa_history")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="구글SA/네이버SA/메타 변경기록을 Google Sheets에 적재합니다."
    )
    parser.add_argument(
        "--date",
        help="Asia/Seoul 기준 테스트 일자. 예: 2026-05-27",
    )
    parser.add_argument(
        "--start",
        help='조회 시작일시. 예: "2026-05-27 00:00:00"',
    )
    parser.add_argument(
        "--end",
        help='조회 종료일시. 예: "2026-05-27 18:00:00"',
    )
    parser.add_argument(
        "--media",
        choices=["all", "google", "naver", "meta"],
        default="all",
        help="테스트용 매체 선택",
    )
    return parser.parse_args()


def _run_google(
    start_at: datetime,
    end_at: datetime,
    collected_at: datetime,
    media_index: CampaignMediaIndex | None = None,
) -> list[dict[str, Any]]:
    mode = settings.GOOGLE_SA_COLLECTION_MODE.lower()
    all_rows: list[dict[str, Any]] = []
    ac_customer_ids = _customer_id_set(settings.GOOGLE_AC_CUSTOMER_IDS)

    for customer_id in _google_customer_ids():
        if mode == "api":
            collector = GoogleAdsChangeCollector(
                settings=settings,
                logger=get_logger("google_sa"),
                customer_id=customer_id,
            )
            source_rows = collector.collect(start_at=start_at, end_at=end_at)
            normalized = normalize_google_records(
                source_rows=source_rows,
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                account_id=customer_id,
            )
        elif mode == "browser":
            collector = GoogleAdsBrowserChangeCollector(
                settings=settings,
                logger=get_logger("google_sa_browser"),
                customer_id=customer_id,
            )
            source_rows = collector.collect(start_at=start_at, end_at=end_at)
            normalized = normalize_google_browser_records(
                source_rows=source_rows,
                collected_at=collected_at,
                start_at=start_at,
                end_at=end_at,
                account_id=customer_id,
            )
        else:
            raise ValueError("GOOGLE_SA_COLLECTION_MODE는 api 또는 browser만 지원합니다.")

        normalized = filter_rows_by_collection_window(
            normalized,
            start_at=start_at,
            end_at=end_at,
            timezone_name=settings.TIMEZONE,
        )
        routed = route_google_media(normalized, ac_customer_ids=ac_customer_ids)
        if media_index:
            routed = media_index.route_rows(routed, logger=get_logger("ad_index"))
        filtered = apply_raw_filters(routed)
        all_rows.extend(attach_row_hash(row) for row in filtered)

    return all_rows


def _google_customer_ids() -> list[str]:
    raw = settings.GOOGLE_ADS_CUSTOMER_IDS or settings.GOOGLE_ADS_CUSTOMER_ID
    customer_ids = [_digits(part) for part in raw.replace(";", ",").split(",")]
    return [customer_id for customer_id in customer_ids if customer_id]


def _customer_id_set(raw: str) -> set[str]:
    return {_digits(part) for part in raw.replace(";", ",").split(",") if _digits(part)}


def _digits(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _run_naver(
    start_at: datetime,
    end_at: datetime,
    collected_at: datetime,
    media_index: CampaignMediaIndex | None = None,
) -> list[dict[str, Any]]:
    collector = NaverSAChangeCollector(settings=settings, logger=get_logger("naver_sa"))
    source_rows = collector.collect(start_at=start_at, end_at=end_at)
    normalized = normalize_naver_records(
        source_rows=source_rows,
        collected_at=collected_at,
        start_at=start_at,
        end_at=end_at,
    )
    normalized = filter_rows_by_collection_window(
        normalized,
        start_at=start_at,
        end_at=end_at,
        timezone_name=settings.TIMEZONE,
    )
    if media_index:
        normalized = media_index.route_rows(normalized, logger=get_logger("ad_index"))
    filtered = apply_raw_filters(normalized)
    return [attach_row_hash(row) for row in filtered]


def _run_meta(
    start_at: datetime,
    end_at: datetime,
    collected_at: datetime,
    media_index: CampaignMediaIndex | None = None,
) -> list[dict[str, Any]]:
    collector = MetaChangeCollector(settings=settings, logger=get_logger("meta"))
    source_rows = collector.collect(start_at=start_at, end_at=end_at)
    normalized = normalize_meta_records(
        source_rows=source_rows,
        collected_at=collected_at,
        start_at=start_at,
        end_at=end_at,
    )
    normalized = filter_rows_by_collection_window(
        normalized,
        start_at=start_at,
        end_at=end_at,
        timezone_name=settings.TIMEZONE,
    )
    if media_index:
        normalized = media_index.route_rows(normalized, logger=get_logger("ad_index"))
    filtered = apply_raw_filters(normalized)
    return [attach_row_hash(row) for row in filtered]


def _run_auto_bid_sheet(
    start_at: datetime,
    end_at: datetime,
    collected_at: datetime,
    media_index: CampaignMediaIndex | None = None,
) -> list[dict[str, Any]]:
    collector = AutoBidSheetChangeCollector(settings=settings, logger=get_logger("auto_bid_sheet"))
    rows = collector.collect(start_at=start_at, end_at=end_at, collected_at=collected_at)
    if media_index:
        rows = media_index.route_rows(rows, logger=get_logger("ad_index"))
    filtered = apply_raw_filters(rows)
    return [attach_row_hash(row) for row in filtered]


def _load_media_index() -> CampaignMediaIndex | None:
    try:
        return load_campaign_media_index(settings=settings, logger=get_logger("ad_index"))
    except Exception as exc:  # noqa: BLE001 - 인덱스 장애 시 기존 매체 판정으로 수집은 계속한다.
        LOGGER.exception("광고 인덱스 매체 매핑 로드 실패, 기존 매체 판정으로 진행합니다: %s", exc)
        return None


def main() -> int:
    args = parse_args()
    start_at, end_at, collected_at = get_collection_window(
        timezone_name=settings.TIMEZONE,
        date_text=args.date,
        start_text=args.start,
        end_text=args.end,
    )
    run_date = start_at.date().isoformat()
    LOGGER.info("조회기간: %s ~ %s (%s)", start_at, end_at, settings.TIMEZONE)

    if args.media == "meta" and not settings.ENABLE_META:
        LOGGER.error("메타 수집이 비활성화되어 있습니다. .env에서 ENABLE_META=true로 변경하세요.")
        return 1

    media_rows: dict[str, list[dict[str, Any]]] = {}
    media_errors: dict[str, str] = {}
    media_index = _load_media_index()

    if args.media in {"all", "google"} and settings.ENABLE_GOOGLE_SA:
        try:
            google_rows = _run_google(start_at, end_at, collected_at, media_index=media_index)
            for row in google_rows:
                media = str(row.get("매체") or "구글SA")
                media_rows.setdefault(media, []).append(row)
            for media in ("구글SA", "구글AC"):
                media_rows.setdefault(media, [])
                LOGGER.info("%s 필터 후 로그: %s건", media, len(media_rows[media]))
        except Exception as exc:  # noqa: BLE001 - 매체별 실패를 분리한다.
            media_errors["구글SA"] = str(exc)
            LOGGER.exception("구글SA 수집 실패: %s", exc)

    if args.media in {"all", "naver"} and settings.ENABLE_NAVER_SA:
        try:
            naver_rows = _run_naver(start_at, end_at, collected_at, media_index=media_index)
            for row in naver_rows:
                media = str(row.get("매체") or "네이버SA")
                media_rows.setdefault(media, []).append(row)
            for media, rows in media_rows.items():
                if media.startswith("네이버"):
                    LOGGER.info("%s 필터 후 로그: %s건", media, len(rows))
        except Exception as exc:  # noqa: BLE001 - 매체별 실패를 분리한다.
            media_errors["네이버SA"] = str(exc)
            LOGGER.exception("네이버SA 수집 실패: %s", exc)

    if args.media in {"all", "naver"} and settings.AUTO_BID_SHEET_ENABLED:
        try:
            auto_bid_rows = _run_auto_bid_sheet(
                start_at,
                end_at,
                collected_at,
                media_index=media_index,
            )
            for row in auto_bid_rows:
                media = str(row.get("매체") or settings.AUTO_BID_FALLBACK_MEDIA)
                media_rows.setdefault(media, []).append(row)
            LOGGER.info("자동입찰시트 필터 후 로그: %s건", len(auto_bid_rows))
        except Exception as exc:  # noqa: BLE001 - 자동입찰시트 장애가 매체 수집 전체를 막지 않게 한다.
            media_errors["자동입찰시트"] = str(exc)
            LOGGER.exception("자동입찰시트 수집 실패: %s", exc)

    if args.media in {"all", "meta"} and settings.ENABLE_META:
        try:
            meta_rows = _run_meta(start_at, end_at, collected_at, media_index=media_index)
            for row in meta_rows:
                media = str(row.get("매체") or "메타")
                media_rows.setdefault(media, []).append(row)
            LOGGER.info("메타 필터 후 로그: %s건", len(media_rows.get("메타", [])))
        except Exception as exc:  # noqa: BLE001 - 매체별 실패를 분리한다.
            media_errors["메타"] = str(exc)
            LOGGER.exception("메타 수집 실패: %s", exc)

    if not media_rows and media_errors:
        LOGGER.error("모든 매체 수집 실패: %s", media_errors)
        return 1

    all_rows = [row for rows in media_rows.values() for row in rows]
    writer = SheetWriter(settings=settings, logger=get_logger("sheet_writer"))
    raw_write_failed = False
    try:
        raw_stats = writer.merge_recent_raw_rows(
            all_rows,
            collected_at=collected_at,
            timezone_name=settings.TIMEZONE,
            days=7,
        )
        LOGGER.info(
            "Raw 최근 7일 merge 완료: 신규 %s건 / 입력 %s건 / 중복 %s건 / 기존 유지 %s건 / 제거 %s건 / 최종 %s건",
            raw_stats["new"],
            raw_stats["input"],
            raw_stats["duplicates"],
            raw_stats["retained_existing"],
            raw_stats["pruned"],
            raw_stats["final"],
        )
    except SheetWriterError as exc:
        raw_write_failed = True
        LOGGER.exception("Raw 적재 실패: %s", exc)

    summary_failed = False
    summary_all_rows: list[dict[str, Any]] | None = None
    if raw_write_failed:
        summary_all_rows = all_rows
    else:
        try:
            summary_all_rows = writer.get_raw_records_for_date(date_text=run_date)
            if media_index:
                summary_all_rows = media_index.route_rows(
                    summary_all_rows,
                    logger=get_logger("ad_index"),
                )
        except SheetWriterError as exc:
            summary_failed = True
            summary_all_rows = all_rows
            LOGGER.exception("Summary 원천 Raw 조회 실패: %s", exc)

    summary_media_names = {
        media for media in media_rows
    } | {
        str(row.get("매체", "")).strip()
        for row in summary_all_rows
        if str(row.get("매체", "")).strip()
    }
    summary_media_to_ensure = [
        media
        for media in summary_media_names
        if media not in {"구글SA", "구글AC", "네이버SA"}
    ]
    if summary_media_to_ensure:
        try:
            writer.ensure_summary_media_columns(sorted(summary_media_to_ensure))
        except SheetWriterError as exc:
            summary_failed = True
            LOGGER.exception("Summary 매체 컬럼 준비 실패: %s", exc)

    summary_texts: dict[str, str] = {}
    for media in sorted(summary_media_names):
        try:
            if raw_write_failed:
                LOGGER.warning(
                    "%s 요약은 Raw 적재 실패로 인해 현재 실행 메모리 데이터를 사용합니다.",
                    media,
                )
            summary_source_rows = [
                row
                for row in summary_all_rows
                if str(row.get("매체", "")).strip() == media
            ]
            if media_index:
                summary_source_rows = media_index.enrich_summary_rows(
                    summary_source_rows,
                    media=media,
                )
            summary_text = build_summary(summary_source_rows, media=media)
            writer.update_summary_cell(
                date_text=run_date,
                media=media,
                summary_text=summary_text,
            )
            summary_texts[media] = summary_text
            LOGGER.info(
                "%s 요약 업데이트 완료: %s",
                media,
                "변경사항 없음" if not summary_text else f"{summary_text.count(chr(10)) + 1}줄",
            )
        except SheetWriterError as exc:
            summary_failed = True
            LOGGER.exception("Summary 적재 실패(%s): %s", media, exc)

    if media_errors:
        LOGGER.warning("일부 매체 수집 실패: %s", media_errors)
    if raw_write_failed or summary_failed:
        return 1
    SlackNotifier(settings=settings, logger=get_logger("slack")).send_summary(
        date_text=run_date,
        start_at=start_at,
        end_at=end_at,
        summaries=summary_texts,
        media_counts=count_rows_by_media(summary_all_rows),
        media_errors=media_errors,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
