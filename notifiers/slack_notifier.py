from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Mapping


SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
DEFAULT_SPREADSHEET_ID = "1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g"
DEFAULT_SUMMARY_SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g/edit?gid=1211091820#gid=1211091820"
)
SLACK_MEDIA_ORDER = ("네이버SA", "구글SA", "구글AC", "네이버 파워컨텐츠", "브랜드검색")
SLACK_MEDIA_ALIASES = {
    "네이버SA_파워콘텐츠": "네이버 파워컨텐츠",
    "네이버 파워콘텐츠": "네이버 파워컨텐츠",
    "BS - 네이버": "브랜드검색",
    "BS_네이버": "브랜드검색",
    "네이버 브랜드검색": "브랜드검색",
    "네이버BS": "브랜드검색",
}


class SlackNotifierError(RuntimeError):
    pass


class SlackNotifier:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger

    def send_summary(
        self,
        *,
        date_text: str,
        start_at: datetime,
        end_at: datetime,
        summaries: dict[str, str] | None = None,
        media_counts: Mapping[str, int] | None = None,
        media_errors: dict[str, str] | None = None,
    ) -> bool:
        del date_text, start_at, end_at, summaries, media_errors

        if not getattr(self.settings, "SLACK_NOTIFICATIONS_ENABLED", False):
            return False

        token = str(getattr(self.settings, "SLACK_BOT_TOKEN", "") or "").strip()
        channel_id = str(getattr(self.settings, "SLACK_CHANNEL_ID", "") or "").strip()
        if not token:
            self.logger.warning("Slack 알림이 켜져 있지만 SLACK_BOT_TOKEN이 없어 발송을 건너뜁니다.")
            return False
        if not channel_id:
            self.logger.warning("Slack 알림이 켜져 있지만 SLACK_CHANNEL_ID가 없어 발송을 건너뜁니다.")
            return False

        message = format_slack_summary_message(
            media_counts=media_counts or {},
            spreadsheet_id=str(getattr(self.settings, "SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID)),
        )
        try:
            self._post_message(token=token, channel_id=channel_id, text=message)
        except SlackNotifierError as exc:
            self.logger.warning("Slack 요약 알림 발송 실패: %s", exc)
            return False

        self.logger.info("Slack 요약 알림 발송 완료: channel=%s", channel_id)
        return True

    def _post_message(self, *, token: str, channel_id: str, text: str) -> None:
        payload = {
            "channel": channel_id,
            "text": text,
            "mrkdwn": True,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        request = urllib.request.Request(
            SLACK_POST_MESSAGE_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        timeout = _int_setting(getattr(self.settings, "SLACK_API_TIMEOUT_SECONDS", "10"), 10)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise SlackNotifierError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise SlackNotifierError(str(exc)) from exc

        try:
            response_json = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise SlackNotifierError(f"Slack 응답 파싱 실패: {response_body}") from exc
        if not response_json.get("ok"):
            raise SlackNotifierError(str(response_json.get("error") or response_json))


def format_slack_summary_message(
    *,
    media_counts: Mapping[str, int],
    spreadsheet_id: str = DEFAULT_SPREADSHEET_ID,
    summary_url: str = DEFAULT_SUMMARY_SPREADSHEET_URL,
) -> str:
    normalized_counts = _normalize_media_counts(media_counts)
    url = str(summary_url or "").strip()
    if not url:
        spreadsheet_id = str(spreadsheet_id or DEFAULT_SPREADSHEET_ID).strip()
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit?gid=1211091820#gid=1211091820"
    lines = [
        f"*<{url}|SA / AC 히스토리 자동 적재 완료>* `수동 변경 내역 기준`",
        "",
    ]
    lines.extend(f"{media}: {normalized_counts.get(media, 0)}건" for media in SLACK_MEDIA_ORDER)
    return "\n".join(lines)


def count_summary_items_from_summary_sheet(
    values: list[list[Any]],
    *,
    date_text: str,
) -> dict[str, int]:
    counts = {media: 0 for media in SLACK_MEDIA_ORDER}
    if len(values) < 2:
        return counts

    header = values[1]
    summary_row = _summary_row_for_date(values, date_text)
    if summary_row is None:
        return counts

    for index, media in enumerate(header):
        normalized_media = _normalize_media_name(media)
        if normalized_media not in counts:
            continue
        cell_value = summary_row[index] if len(summary_row) > index else ""
        counts[normalized_media] += _count_non_empty_lines(cell_value)
    return counts


def build_slack_summary_message(
    *,
    media_counts: Mapping[str, int] | None = None,
    date_text: str = "",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    summaries: dict[str, str] | None = None,
    media_errors: dict[str, str] | None = None,
    max_chars: int = 35000,
) -> str:
    del date_text, start_at, end_at, summaries, media_errors, max_chars
    return format_slack_summary_message(media_counts=media_counts or {})


def _normalize_media_counts(media_counts: Mapping[str, int]) -> dict[str, int]:
    normalized = {media: 0 for media in SLACK_MEDIA_ORDER}
    for media, count in media_counts.items():
        key = _normalize_media_name(media)
        if key not in normalized:
            continue
        try:
            normalized[key] += int(count)
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_media_name(media: Any) -> str:
    text = str(media or "").strip()
    return SLACK_MEDIA_ALIASES.get(text, text)


def _summary_row_for_date(values: list[list[Any]], date_text: str) -> list[Any] | None:
    target = str(date_text or "").strip()
    for row in values[2:]:
        if row and str(row[0] or "").strip() == target:
            return row
    return None


def _count_non_empty_lines(value: Any) -> int:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return sum(1 for line in text.split("\n") if line.strip())


def _escape_slack(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _int_setting(value: Any, default: int) -> int:
    try:
        return max(1, int(str(value or "").strip()))
    except (TypeError, ValueError):
        return default
