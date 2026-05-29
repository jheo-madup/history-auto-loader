from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings as default_settings
from utils.logger import get_logger
from utils.state_loader import ensure_local_file


class NaverSessionExpiredError(RuntimeError):
    pass


class NaverSAChangeCollector:
    def __init__(self, settings: Any, logger: Any) -> None:
        self.settings = settings
        self.logger = logger

    def collect(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        if self.settings.NAVER_HISTORY_XLSX_PATH:
            self.logger.info("네이버SA 로컬 xlsx 파일을 사용합니다: %s", self.settings.NAVER_HISTORY_XLSX_PATH)
            return self._read_xlsx(Path(self.settings.NAVER_HISTORY_XLSX_PATH))

        downloaded = self.download_history_xlsx(start_at=start_at, end_at=end_at)
        return self._read_xlsx(downloaded)

    def download_history_xlsx(self, start_at: datetime, end_at: datetime) -> Path:
        if not self.settings.NAVER_HISTORY_URL:
            raise ValueError(
                "NAVER_HISTORY_URL이 비어 있습니다. 네이버 검색광고 이력관리 화면 URL을 환경변수로 설정하세요."
            )

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        storage_state = ensure_local_file(
            path=self.settings.NAVER_STORAGE_STATE_PATH,
            inline_content=self.settings.NAVER_STORAGE_STATE_JSON,
            secret_id=self.settings.NAVER_STORAGE_STATE_SECRET_ID,
            gcs_uri=self.settings.NAVER_STORAGE_STATE_GCS_URI,
            project_id=self.settings.PROJECT_ID,
            logger=self.logger,
            label="Naver storage_state",
        )

        if not storage_state or not Path(storage_state).exists():
            if self.settings.NAVER_ALLOW_INTERACTIVE_LOGIN:
                self.save_login_state()
                storage_state = self.settings.NAVER_STORAGE_STATE_PATH
            else:
                raise FileNotFoundError(
                    "네이버 storage_state 파일이 없습니다. 로컬에서 로그인 상태를 저장하거나 Secret Manager/GCS로 공급하세요."
                )

        download_dir = Path(self.settings.NAVER_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)
        output_path = download_dir / f"naver_sa_history_{end_at.strftime('%Y%m%d_%H%M%S')}.xlsx"

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.settings.NAVER_HEADLESS,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    storage_state=storage_state,
                    accept_downloads=True,
                    locale="ko-KR",
                    timezone_id=self.settings.TIMEZONE,
                )
                page = context.new_page()
                page.goto(self.settings.NAVER_HISTORY_URL, wait_until="networkidle", timeout=90000)
                self._raise_if_logged_out(page)

                self._fill_date_range(page, start_at=start_at, end_at=end_at)
                self._click_search(page)

                with page.expect_download(timeout=120000) as download_info:
                    self._click_download(page)
                download = download_info.value
                download.save_as(str(output_path))

                context.close()
                browser.close()
        except NaverSessionExpiredError:
            raise
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"네이버SA 다운로드 타임아웃: {exc}") from exc

        self.logger.info("네이버SA xlsx 다운로드 완료: %s", output_path)
        return output_path

    def save_login_state(self) -> Path:
        from playwright.sync_api import sync_playwright

        if not self.settings.NAVER_HISTORY_URL:
            raise ValueError("NAVER_HISTORY_URL이 비어 있어 로그인 상태를 저장할 수 없습니다.")

        target = Path(self.settings.NAVER_STORAGE_STATE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info("브라우저에서 네이버 로그인을 완료하세요. 완료 후 창을 닫지 말고 대기하면 상태를 저장합니다.")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(locale="ko-KR", timezone_id=self.settings.TIMEZONE)
            page = context.new_page()
            page.goto(self.settings.NAVER_HISTORY_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(180000)
            context.storage_state(path=str(target))
            context.close()
            browser.close()
        self.logger.info("네이버 storage_state 저장 완료: %s", target)
        return target

    def _read_xlsx(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"네이버SA xlsx 파일을 찾을 수 없습니다: {path}")

        df = pd.read_excel(path, dtype=str).fillna("")
        records = df.to_dict(orient="records")
        self.logger.info("네이버SA xlsx 원본 수집: %s건", len(records))
        return records

    def _fill_date_range(self, page: Any, start_at: datetime, end_at: datetime) -> None:
        start_selector = self.settings.NAVER_START_DATE_SELECTOR
        end_selector = self.settings.NAVER_END_DATE_SELECTOR
        if start_selector:
            page.locator(start_selector).first.fill(start_at.strftime("%Y-%m-%d"))
        if end_selector:
            page.locator(end_selector).first.fill(end_at.strftime("%Y-%m-%d"))

    def _click_search(self, page: Any) -> None:
        if self.settings.NAVER_SEARCH_BUTTON_SELECTOR:
            page.locator(self.settings.NAVER_SEARCH_BUTTON_SELECTOR).first.click(timeout=30000)
            page.wait_for_load_state("networkidle", timeout=60000)
            return
        for text in ("조회", "검색"):
            locator = page.get_by_text(text, exact=False).first
            if locator.count():
                locator.click(timeout=10000)
                page.wait_for_load_state("networkidle", timeout=60000)
                return

    def _click_download(self, page: Any) -> None:
        if self.settings.NAVER_DOWNLOAD_BUTTON_SELECTOR:
            page.locator(self.settings.NAVER_DOWNLOAD_BUTTON_SELECTOR).first.click(timeout=30000)
            return
        for text in ("엑셀 다운로드", "다운로드", "Excel", "xlsx"):
            locator = page.get_by_text(text, exact=False).first
            if locator.count():
                locator.click(timeout=30000)
                return
        raise RuntimeError("네이버SA 다운로드 버튼을 찾지 못했습니다. NAVER_DOWNLOAD_BUTTON_SELECTOR를 설정하세요.")

    @staticmethod
    def _raise_if_logged_out(page: Any) -> None:
        url = page.url.lower()
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            body_text = ""

        logged_out_markers = ("nid.naver.com", "로그인", "login")
        if any(marker in url for marker in ("nid.naver.com", "login")) or any(
            marker in body_text for marker in logged_out_markers
        ):
            raise NaverSessionExpiredError(
                "네이버 로그인 세션 만료 가능성: storage_state를 갱신하세요."
            )


def _cli() -> int:
    parser = argparse.ArgumentParser(description="네이버SA Playwright 보조 명령")
    parser.add_argument("--login", action="store_true", help="브라우저 로그인 후 storage_state 저장")
    parser.add_argument("--download", action="store_true", help="오늘 이력 xlsx 다운로드 테스트")
    args = parser.parse_args()

    logger = get_logger("naver_sa_cli")
    collector = NaverSAChangeCollector(settings=default_settings, logger=logger)
    if args.login:
        collector.save_login_state()
        return 0
    if args.download:
        from utils.datetime_utils import get_collection_window

        start_at, end_at, _ = get_collection_window(default_settings.TIMEZONE)
        collector.download_history_xlsx(start_at=start_at, end_at=end_at)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
