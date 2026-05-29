from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from collectors.auto_bid_sheet_change import _optional_column, _required_column, build_auto_bid_change_rows
from processors.filters import should_keep_raw
from processors.summarizer import build_summary
from utils.hash_utils import build_row_hash
from writers.ad_index_reader import CampaignMediaIndex
from writers.sheet_writer import dedupe_raw_records, filter_recent_raw_records


class HistoryLogicTest(unittest.TestCase):
    def test_simple_daily_budget_change_is_excluded(self) -> None:
        row = _row(
            old_value="100,000원",
            new_value="150,000원",
            content="변경 전\n하루예산: 100,000원\n변경 후\n하루예산: 150,000원",
        )

        self.assertFalse(should_keep_raw(row))
        self.assertEqual(build_summary([row], "네이버SA"), "")

    def test_budget_change_with_tcpa_campaign_name_is_excluded(self) -> None:
        row = _row(
            media="구글SA",
            campaign="gmo_논브랜드_tCPA_onlyAPP",
            ad_group="",
            change_type="예산 1개가 감소함",
            field="예산",
            content="예산 1개가 감소함\n  gmo_논브랜드_tCPA_onlyAPP: 예산 금액이(가) ₩1,200,000에서 ₩550,000(으)로 변경됨",
        )

        self.assertFalse(should_keep_raw(row))
        self.assertEqual(build_summary([row], "구글SA"), "")

    def test_new_daily_budget_setting_is_kept_and_summarized(self) -> None:
        row = _row(
            old_value="",
            new_value="100,000원",
            content="변경 전\n하루예산 사용여부: 사용안함\n하루예산: 0원\n변경 후\n하루예산 사용여부: 사용함\n하루예산: 100,000원",
        )

        self.assertTrue(should_keep_raw(row))
        self.assertEqual(
            build_summary([row], "네이버SA"),
            "[캠페인A] 일예산 신규 설정: 100,000원",
        )

    def test_api_actor_is_excluded(self) -> None:
        row = _row(actor="dreamful7:naver(API)", content="키워드\n변경 전\n입찰가: 100\n변경 후\n입찰가: 200")

        self.assertFalse(should_keep_raw(row))
        self.assertEqual(build_summary([row], "네이버SA"), "")

    def test_media_index_matches_campaign_then_ad_group(self) -> None:
        index = CampaignMediaIndex(
            campaign_to_media={"캠페인a": "구글SA"},
            ad_group_to_media={"그룹b": "네이버 파워컨텐츠"},
            campaign_to_summary_entity={},
            ad_group_to_summary_entity={},
            summary_entity_media="메타",
        )

        routed = index.route_rows(
            [
                {"캠페인명": "캠페인A", "광고그룹명": "그룹B", "매체": "네이버SA"},
                {"캠페인명": "", "광고그룹명": "그룹B_g", "매체": "네이버SA"},
            ]
        )

        self.assertEqual(routed[0]["매체"], "구글SA")
        self.assertEqual(routed[1]["매체"], "네이버 파워컨텐츠")

    def test_brand_search_fallback_routes_to_bs_naver(self) -> None:
        index = CampaignMediaIndex(
            campaign_to_media={},
            ad_group_to_media={},
            campaign_to_summary_entity={},
            ad_group_to_summary_entity={},
            summary_entity_media="메타",
        )

        routed = index.route_rows(
            [{"캠페인명": "브랜드검색", "광고그룹명": "2508_금융상품_ml-listing", "매체": "네이버SA"}]
        )

        self.assertEqual(routed[0]["매체"], "BS - 네이버")

    def test_auto_bid_target_rank_change_is_raw_and_summary(self) -> None:
        now = datetime(2026, 5, 29, 13, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        rows = build_auto_bid_change_rows(
            current_records=[{"keyword": "삼성증권", "target_rank": "5", "campaign": "", "ad_group": "", "media": ""}],
            previous_snapshot={"삼성증권": {"target_rank": "3"}},
            collected_at=now,
            start_at=now.replace(hour=0),
            end_at=now,
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(should_keep_raw(rows[0]))
        self.assertEqual(
            build_summary(rows, "네이버SA"),
            "[삼성증권] 목표순위 3순위 → 5순위 변경",
        )

    def test_auto_bid_column_aliases_match_operating_sheet_headers(self) -> None:
        header = ["키워드", "캠페인명", "광고그룹명", "목표 순위"]

        self.assertEqual(_required_column(header, "목표순위", aliases=("목표 순위",)), 3)
        self.assertEqual(_optional_column(header, "Campaign", aliases=("캠페인명",)), 1)
        self.assertEqual(_optional_column(header, "Ad Group", aliases=("광고그룹명",)), 2)

    def test_auto_bid_new_keyword_without_old_rank_is_summarized(self) -> None:
        now = datetime(2026, 5, 29, 13, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        rows = build_auto_bid_change_rows(
            current_records=[{"keyword": "해외주식", "target_rank": "5", "campaign": "nmo_일반", "ad_group": "m_일반", "media": ""}],
            previous_snapshot={"삼성증권": {"target_rank": "3"}},
            collected_at=now,
            start_at=now.replace(hour=0),
            end_at=now,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["캠페인명"], "nmo_일반")
        self.assertEqual(rows[0]["광고그룹명"], "m_일반")
        self.assertEqual(build_summary(rows, "네이버SA"), "[해외주식] 목표순위 5순위로 변경")

    def test_many_asset_changes_are_summarized_by_count(self) -> None:
        rows = [
            _row(
                level="소재",
                change_type="소재 On/Off",
                field="On/Off",
                ad_group="그룹A",
                ad=f"소재{i}",
                content=f"소재{i}\n변경 전\nOn/Off: ON\n변경 후\nOn/Off: OFF",
            )
            for i in range(5)
        ]

        self.assertEqual(build_summary(rows, "네이버SA"), "[그룹A] 소재 5건 변경")

    def test_google_responsive_search_ad_off_is_not_tcpa_change(self) -> None:
        row = _row(
            media="구글SA",
            campaign="gmo_논브랜드_tCPA_onlyAPP",
            ad_group="m_국내_일반",
            change_type="반응형 검색 광고 1개가 변경됨",
            field="",
            content="반응형 검색 광고 1개가 변경됨\n  상태이(가) 운영중에서 일시중지됨(으)로 변경됨",
        )
        row["raw_text"] = '{"캠페인":"gmo_논브랜드_tCPA_onlyAPP","변경사항":"반응형 검색 광고 1개가 변경됨"}'

        self.assertTrue(should_keep_raw(row))
        self.assertEqual(build_summary([row], "구글SA"), "[m_국내_일반] 소재 OFF 1건")

    def test_row_hash_ignores_media_after_index_routing(self) -> None:
        naver_row = _row(campaign="브랜드검색", ad_group="2508_금융상품_ml-listing", media="네이버SA")
        bs_row = {**naver_row, "매체": "BS - 네이버"}

        self.assertEqual(build_row_hash(naver_row), build_row_hash(bs_row))

    def test_raw_dedupe_prefers_specific_media(self) -> None:
        naver_row = _row(campaign="브랜드검색", ad_group="2508_금융상품_ml-listing", media="네이버SA")
        bs_row = {**naver_row, "매체": "BS - 네이버"}

        deduped = dedupe_raw_records([naver_row, bs_row])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["매체"], "BS - 네이버")

    def test_raw_keeps_only_recent_seven_days(self) -> None:
        now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        rows = [
            {"일자": (now.date() - timedelta(days=offset)).isoformat(), "변경일시": ""}
            for offset in range(10)
        ]

        recent = filter_recent_raw_records(rows, collected_at=now, timezone_name="Asia/Seoul", days=7)

        self.assertEqual(len(recent), 7)
        self.assertEqual(recent[-1]["일자"], "2026-05-23")


def _row(
    *,
    media: str = "네이버SA",
    actor: str = "user@company.com",
    campaign: str = "캠페인A",
    ad_group: str = "그룹A",
    ad: str = "",
    keyword: str = "",
    level: str = "광고그룹",
    change_type: str = "광고그룹 변경",
    field: str = "하루예산",
    old_value: str = "",
    new_value: str = "",
    content: str = "",
) -> dict[str, str]:
    return {
        "일자": "2026-05-29",
        "매체": media,
        "변경일시": "2026-05-29 12:00:00",
        "변경자": actor,
        "캠페인명": campaign,
        "광고그룹명": ad_group,
        "소재명": ad,
        "키워드명": keyword,
        "변경레벨": level,
        "변경유형": change_type,
        "변경작업": "수정",
        "변경필드": field,
        "이전값": old_value,
        "변경값": new_value,
        "변경내용": content,
        "원본리소스명": "",
        "raw_text": content,
        "row_hash": "",
    }


if __name__ == "__main__":
    unittest.main()
