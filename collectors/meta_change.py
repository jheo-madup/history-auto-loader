from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings as default_settings
from utils.logger import get_logger
from utils.state_loader import ensure_local_file


class MetaSessionExpiredError(RuntimeError):
    pass


class MetaChangeCollector:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger

    def collect(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        if self.settings.META_HISTORY_FILE_PATH:
            local_path = Path(self.settings.META_HISTORY_FILE_PATH)
            self.logger.info("메타 로컬 변경이력 파일을 사용합니다: %s", local_path)
            return self._read_history_file(local_path)

        downloaded = self.download_history_file(start_at=start_at, end_at=end_at)
        return self._read_history_file(downloaded)

    def download_history_file(self, start_at: datetime, end_at: datetime) -> Path:
        if not self.settings.META_HISTORY_URL:
            raise ValueError("META_HISTORY_URL이 비어 있습니다. Meta 변경 이력 화면 URL을 설정하세요.")

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        storage_state = ensure_local_file(
            path=self.settings.META_STORAGE_STATE_PATH,
            inline_content=self.settings.META_STORAGE_STATE_JSON,
            secret_id=self.settings.META_STORAGE_STATE_SECRET_ID,
            gcs_uri=self.settings.META_STORAGE_STATE_GCS_URI,
            project_id=self.settings.PROJECT_ID,
            logger=self.logger,
            label="Meta storage_state",
        )

        if not storage_state or not Path(storage_state).exists():
            if self.settings.META_ALLOW_INTERACTIVE_LOGIN:
                self.save_login_state()
                storage_state = self.settings.META_STORAGE_STATE_PATH
            else:
                raise FileNotFoundError(
                    "Meta storage_state 파일이 없습니다. 로컬에서 로그인 상태를 저장하거나 Secret Manager/GCS로 공급하세요."
                )

        download_dir = Path(self.settings.META_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.settings.META_HEADLESS,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    storage_state=storage_state,
                    accept_downloads=True,
                    locale="ko-KR",
                    timezone_id=self.settings.TIMEZONE,
                )
                page = context.new_page()
                page.goto(self.settings.META_HISTORY_URL, wait_until="networkidle", timeout=120000)
                self._raise_if_logged_out(page)
                self._fill_date_range(page, start_at=start_at, end_at=end_at)
                self._click_search(page)

                with page.expect_download(timeout=120000) as download_info:
                    self._click_download(page)
                download = download_info.value
                suggested_name = download.suggested_filename or "meta_history.xlsx"
                extension = Path(suggested_name).suffix or ".xlsx"
                output_path = download_dir / f"meta_history_{end_at.strftime('%Y%m%d_%H%M%S')}{extension}"
                download.save_as(str(output_path))

                context.close()
                browser.close()
        except MetaSessionExpiredError:
            raise
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"메타 변경이력 다운로드 타임아웃: {exc}") from exc

        self.logger.info("메타 변경이력 다운로드 완료: %s", output_path)
        return output_path

    def save_login_state(self) -> Path:
        from playwright.sync_api import sync_playwright

        if not self.settings.META_HISTORY_URL:
            raise ValueError("META_HISTORY_URL이 비어 있어 로그인 상태를 저장할 수 없습니다.")

        target = Path(self.settings.META_STORAGE_STATE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info("브라우저에서 Meta 로그인을 완료하세요. 변경 이력 화면이 보이면 대기 후 세션을 저장합니다.")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(locale="ko-KR", timezone_id=self.settings.TIMEZONE)
            page = context.new_page()
            page.goto(self.settings.META_HISTORY_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(180000)
            context.storage_state(path=str(target))
            context.close()
            browser.close()
        self.logger.info("Meta storage_state 저장 완료: %s", target)
        return target

    def _read_history_file(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"메타 변경이력 파일을 찾을 수 없습니다: {path}")

        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(path, dtype=str).fillna("")
        elif suffix == ".csv":
            df = self._read_csv(path)
        else:
            raise ValueError(f"지원하지 않는 메타 변경이력 파일 형식입니다: {path.suffix}")

        records = df.to_dict(orient="records")
        self.logger.info("메타 원본 수집: %s건", len(records))
        return records

    @staticmethod
    def _read_csv(path: Path) -> pd.DataFrame:
        for encoding in ("utf-8-sig", "utf-16", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
            except UnicodeError:
                continue
        return pd.read_csv(path, dtype=str).fillna("")

    def _fill_date_range(self, page: Any, start_at: datetime, end_at: datetime) -> None:
        if self.settings.META_START_DATE_SELECTOR:
            page.locator(self.settings.META_START_DATE_SELECTOR).first.fill(start_at.strftime("%Y-%m-%d"))
        if self.settings.META_END_DATE_SELECTOR:
            page.locator(self.settings.META_END_DATE_SELECTOR).first.fill(end_at.strftime("%Y-%m-%d"))

    def _click_search(self, page: Any) -> None:
        if self.settings.META_SEARCH_BUTTON_SELECTOR:
            page.locator(self.settings.META_SEARCH_BUTTON_SELECTOR).first.click(timeout=30000)
            page.wait_for_load_state("networkidle", timeout=60000)
            return
        for pattern in (r"적용", r"조회", r"검색", r"Apply", r"Search"):
            locator = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            try:
                if locator.count():
                    locator.click(timeout=10000)
                    page.wait_for_load_state("networkidle", timeout=60000)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _click_download(self, page: Any) -> None:
        if self.settings.META_DOWNLOAD_BUTTON_SELECTOR:
            page.locator(self.settings.META_DOWNLOAD_BUTTON_SELECTOR).first.click(timeout=30000)
            return
        for pattern in (r"내보내기", r"다운로드", r"Export", r"Download"):
            for finder in (
                lambda: page.get_by_role("button", name=re.compile(pattern, re.I)).first,
                lambda: page.get_by_label(re.compile(pattern, re.I)).first,
                lambda: page.get_by_text(re.compile(pattern, re.I)).first,
            ):
                try:
                    locator = finder()
                    if locator.count():
                        locator.click(timeout=30000)
                        return
                except Exception:  # noqa: BLE001
                    continue
        raise RuntimeError("메타 다운로드 버튼을 찾지 못했습니다. META_DOWNLOAD_BUTTON_SELECTOR를 설정하세요.")

    @staticmethod
    def _raise_if_logged_out(page: Any) -> None:
        url = page.url.lower()
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=5000).lower()
        except Exception:  # noqa: BLE001
            body_text = ""

        if any(marker in url for marker in ("login", "facebook.com/login", "accountscenter")) or any(
            marker in body_text for marker in ("log in", "로그인", "login")
        ):
            raise MetaSessionExpiredError("Meta 로그인 세션 만료 가능성: storage_state를 갱신하세요.")


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Meta Playwright 보조 명령")
    parser.add_argument("--login", action="store_true", help="브라우저 로그인 후 storage_state 저장")
    parser.add_argument("--download", action="store_true", help="오늘 변경이력 다운로드 테스트")
    args = parser.parse_args()

    logger = get_logger("meta_cli")
    collector = MetaChangeCollector(settings=default_settings, logger=logger)
    if args.login:
        collector.save_login_state()
        return 0
    if args.download:
        from utils.datetime_utils import get_collection_window

        start_at, end_at, _ = get_collection_window(default_settings.TIMEZONE)
        collector.download_history_file(start_at=start_at, end_at=end_at)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
