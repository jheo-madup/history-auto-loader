from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


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
        summaries: dict[str, str],
        media_errors: dict[str, str] | None = None,
    ) -> bool:
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

        message = build_slack_summary_message(
            date_text=date_text,
            start_at=start_at,
            end_at=end_at,
            summaries=summaries,
            media_errors=media_errors or {},
            max_chars=_int_setting(getattr(self.settings, "SLACK_MESSAGE_MAX_CHARS", "35000"), 35000),
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


def build_slack_summary_message(
    *,
    date_text: str,
    start_at: datetime,
    end_at: datetime,
    summaries: dict[str, str],
    media_errors: dict[str, str] | None = None,
    max_chars: int = 35000,
) -> str:
    lines = [
        f"*SA 변경기록 요약* `{_escape_slack(date_text)}`",
        f"조회기간: `{_escape_slack(_time_text(start_at))}` ~ `{_escape_slack(_time_text(end_at))}`",
    ]

    if summaries:
        for media in sorted(summaries):
            summary_text = str(summaries.get(media) or "").strip() or "변경사항 없음"
            lines.append("")
            lines.append(f"*{_escape_slack(media)}*")
            lines.extend(_escape_slack(line) for line in summary_text.splitlines())
    else:
        lines.append("")
        lines.append("변경사항 없음")

    if media_errors:
        lines.append("")
        lines.append("*수집 오류*")
        for media, error in sorted(media_errors.items()):
            lines.append(f"- {_escape_slack(media)}: {_escape_slack(error)}")

    message = "\n".join(lines)
    if len(message) <= max_chars:
        return message
    suffix = "\n… Slack 메시지 길이 제한으로 일부 내용이 생략되었습니다."
    return message[: max(0, max_chars - len(suffix))].rstrip() + suffix


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
