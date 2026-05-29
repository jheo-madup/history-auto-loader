from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from collectors.auto_bid_sheet_change import build_auto_bid_change_rows
from processors.filters import should_keep_raw
from processors.summarizer import build_summary
from writers.ad_index_reader import CampaignMediaIndex
from writers.sheet_writer import filter_recent_raw_records


class HistoryLogicTest(unittest.TestCase):
    def test_simple_daily_budget_change_is_excluded(self) -> None:
        row = _row(
            old_value="100,000원",
            new_value="150,000원",
            content="변경 전\n하루예산: 100,000원\n변경 후\n하루예산: 150,000원",
        )

        self.assertFalse(should_keep_raw(row))
        self.assertEqual(build_summary([row], "네이버SA"), "")

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
