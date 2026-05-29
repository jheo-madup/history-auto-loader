from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.state_loader import ensure_local_file


class GoogleAdsChangeCollector:
    def __init__(self, settings: Any, logger: Any, customer_id: str | None = None) -> None:
        self.settings = settings
        self.logger = logger
        self.customer_id = (customer_id or settings.GOOGLE_ADS_CUSTOMER_ID or "").replace("-", "").strip()

    def collect(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        if not self.customer_id:
            raise ValueError("GOOGLE_ADS_CUSTOMER_ID가 비어 있습니다.")

        from google.ads.googleads.client import GoogleAdsClient
        from google.protobuf.json_format import MessageToDict

        config_path = ensure_local_file(
            path=self.settings.GOOGLE_ADS_CONFIG_PATH,
            inline_content=self.settings.GOOGLE_ADS_YAML_CONTENT,
            secret_id=self.settings.GOOGLE_ADS_CONFIG_SECRET_ID,
            gcs_uri=self.settings.GOOGLE_ADS_CONFIG_GCS_URI,
            project_id=self.settings.PROJECT_ID,
            logger=self.logger,
            label="Google Ads YAML",
        )

        if config_path and Path(config_path).exists():
            client = GoogleAdsClient.load_from_storage(path=config_path)
        else:
            self.logger.info("google-ads.yaml 파일이 없어 환경변수 기반 인증을 시도합니다.")
            client = GoogleAdsClient.load_from_env()

        if self.settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
            client.login_customer_id = self.settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID

        google_ads_service = client.get_service("GoogleAdsService")
        query = self._build_query(start_at=start_at, end_at=end_at)
        self.logger.info("Google Ads change_event 조회 시작 customer_id=%s", self.customer_id)

        rows: list[dict[str, Any]] = []
        stream = google_ads_service.search_stream(
            customer_id=self.customer_id,
            query=query,
        )
        for batch in stream:
            for result in batch.results:
                event = result.change_event
                changed_fields = list(getattr(event.changed_fields, "paths", []))
                rows.append(
                    {
                        "media": "구글SA",
                        "account_id": self.customer_id,
                        "change_date_time": event.change_date_time,
                        "user_email": event.user_email,
                        "change_resource_type": self._enum_name(event.change_resource_type),
                        "change_resource_name": event.change_resource_name,
                        "resource_change_operation": self._enum_name(
                            event.resource_change_operation
                        ),
                        "changed_fields": changed_fields,
                        "old_resource": self._message_to_dict(event.old_resource, MessageToDict),
                        "new_resource": self._message_to_dict(event.new_resource, MessageToDict),
                    }
                )

        self.logger.info("Google Ads change_event 원본 수집: %s건", len(rows))
        return rows

    @staticmethod
    def _build_query(start_at: datetime, end_at: datetime) -> str:
        start_text = start_at.strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_at.strftime("%Y-%m-%d %H:%M:%S")
        return f"""
            SELECT
              change_event.change_date_time,
              change_event.user_email,
              change_event.change_resource_type,
              change_event.change_resource_name,
              change_event.resource_change_operation,
              change_event.changed_fields,
              change_event.old_resource,
              change_event.new_resource
            FROM change_event
            WHERE change_event.change_date_time >= '{start_text}'
              AND change_event.change_date_time <= '{end_text}'
            ORDER BY change_event.change_date_time ASC
            LIMIT 10000
        """

    @staticmethod
    def _enum_name(value: Any) -> str:
        name = getattr(value, "name", None) or str(value)
        text = str(name).rsplit(".", 1)[-1]
        chars: list[str] = []
        for index, char in enumerate(text):
            if char.isupper() and index > 0 and text[index - 1].islower():
                chars.append("_")
            chars.append(char)
        return "".join(chars).upper()

    @staticmethod
    def _message_to_dict(message: Any, converter: Any) -> dict[str, Any]:
        try:
            pb = message._pb if hasattr(message, "_pb") else message
            return converter(pb, preserving_proto_field_name=True)
        except Exception:  # noqa: BLE001 - 원본 보존 보조 로직이다.
            try:
                return json.loads(str(message))
            except Exception:  # noqa: BLE001
                return {"text": str(message)}
