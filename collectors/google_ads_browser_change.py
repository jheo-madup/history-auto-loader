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


class GoogleAdsSessionExpiredError(RuntimeError):
    pass


class GoogleAdsBrowserChangeCollector:
    def __init__(self, settings: Any, logger: Any, customer_id: str | None = None) -> None:
        self.settings = settings
        self.logger = logger
        self.customer_id = (customer_id or settings.GOOGLE_ADS_CUSTOMER_ID or "").replace("-", "").strip()

    def collect(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        if self.settings.GOOGLE_ADS_HISTORY_FILE_PATH:
            local_path = Path(self.settings.GOOGLE_ADS_HISTORY_FILE_PATH)
            self.logger.info("구글SA 로컬 변경이력 파일을 사용합니다: %s", local_path)
            return self._read_history_file(local_path)

        downloaded = self.download_history_file(start_at=start_at, end_at=end_at)
        if downloaded is None:
            return []
        return self._read_history_file(downloaded)

    def download_history_file(self, start_at: datetime, end_at: datetime) -> Path | None:
        history_url = self.settings.GOOGLE_ADS_HISTORY_URL
        if not history_url:
            raise ValueError(
                "GOOGLE_ADS_HISTORY_URL이 비어 있습니다. Google Ads 변경 이력 화면 URL을 설정하세요."
            )
        target_url = self._target_history_url(history_url)

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        storage_state = ensure_local_file(
            path=self.settings.GOOGLE_ADS_STORAGE_STATE_PATH,
            inline_content=self.settings.GOOGLE_ADS_STORAGE_STATE_JSON,
            secret_id=self.settings.GOOGLE_ADS_STORAGE_STATE_SECRET_ID,
            gcs_uri=self.settings.GOOGLE_ADS_STORAGE_STATE_GCS_URI,
            project_id=self.settings.PROJECT_ID,
            logger=self.logger,
            label="Google Ads storage_state",
        )

        if not storage_state or not Path(storage_state).exists():
            if self.settings.GOOGLE_ADS_ALLOW_INTERACTIVE_LOGIN:
                self.save_login_state()
                storage_state = self.settings.GOOGLE_ADS_STORAGE_STATE_PATH
            else:
                raise FileNotFoundError(
                    "Google Ads storage_state 파일이 없습니다. 로컬에서 로그인 상태를 저장하거나 Secret Manager/GCS로 공급하세요."
                )

        download_dir = Path(self.settings.GOOGLE_ADS_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)

        playwright = None
        browser = None
        context = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=self.settings.GOOGLE_ADS_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                storage_state=storage_state,
                accept_downloads=True,
                locale="ko-KR",
                timezone_id=self.settings.TIMEZONE,
            )
            page = context.new_page()
            page.goto(target_url, wait_until="networkidle", timeout=120000)
            self._select_account_if_needed(page)
            self._raise_if_logged_out(page)

            self._fill_date_range(page, start_at=start_at, end_at=end_at)
            if (
                self.settings.GOOGLE_ADS_SEARCH_BUTTON_SELECTOR
                or self.settings.GOOGLE_ADS_START_DATE_SELECTOR
                or self.settings.GOOGLE_ADS_END_DATE_SELECTOR
            ):
                self._click_apply_or_search(page)
            self._dismiss_blocking_dialogs(page)
            if self._has_no_changes(page):
                self.logger.info("Google Ads 변경이력 없음: %s", self.customer_id or "default")
                return None

            with page.expect_download(timeout=120000) as download_info:
                self._click_download(page)
            download = download_info.value
            suggested_name = download.suggested_filename or "google_ads_history.xlsx"
            extension = Path(suggested_name).suffix or ".xlsx"
            account_part = self.customer_id or "default"
            output_path = download_dir / (
                f"google_ads_history_{account_part}_{end_at.strftime('%Y%m%d_%H%M%S')}{extension}"
            )
            download.save_as(str(output_path))
        except GoogleAdsSessionExpiredError:
            raise
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"구글SA 변경이력 다운로드 타임아웃: {exc}") from exc
        finally:
            for target in (context, browser, playwright):
                if target is None:
                    continue
                try:
                    if target is playwright:
                        target.stop()
                    else:
                        target.close()
                except Exception:  # noqa: BLE001 - cleanup failure should not mask collection result.
                    pass

        self.logger.info("구글SA 변경이력 다운로드 완료: %s", output_path)
        return output_path

    def save_login_state(self) -> Path:
        from playwright.sync_api import sync_playwright

        if not self.settings.GOOGLE_ADS_HISTORY_URL:
            raise ValueError("GOOGLE_ADS_HISTORY_URL이 비어 있어 로그인 상태를 저장할 수 없습니다.")

        target = Path(self.settings.GOOGLE_ADS_STORAGE_STATE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "브라우저에서 Google Ads 로그인을 완료하세요. 변경 이력 화면이 보이면 대기 후 세션을 저장합니다."
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(locale="ko-KR", timezone_id=self.settings.TIMEZONE)
            page = context.new_page()
            page.goto(self.settings.GOOGLE_ADS_HISTORY_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(180000)
            context.storage_state(path=str(target))
            context.close()
            browser.close()
        self.logger.info("Google Ads storage_state 저장 완료: %s", target)
        return target

    def _read_history_file(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"구글SA 변경이력 파일을 찾을 수 없습니다: {path}")

        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            df = self._read_excel(path)
        elif suffix == ".csv":
            df = self._read_csv(path)
        else:
            raise ValueError(f"지원하지 않는 구글SA 변경이력 파일 형식입니다: {path.suffix}")

        records = df.to_dict(orient="records")
        self.logger.info("구글SA 브라우저 원본 수집: %s건", len(records))
        return records

    @staticmethod
    def _read_excel(path: Path) -> pd.DataFrame:
        raw = pd.read_excel(path, dtype=str, header=None).fillna("")
        header_index = None
        required_headers = {"날짜 및 시간", "사용자", "변경사항"}

        for index, row in raw.iterrows():
            values = {str(value).strip() for value in row.tolist() if str(value).strip()}
            if required_headers.issubset(values):
                header_index = index
                break

        if header_index is None:
            return pd.read_excel(path, dtype=str).fillna("")

        headers = [str(value).strip() for value in raw.iloc[header_index].tolist()]
        data = raw.iloc[header_index + 1 :].copy()
        data.columns = headers
        data = data.loc[:, [column for column in data.columns if column]]
        return data.fillna("")

    @staticmethod
    def _read_csv(path: Path) -> pd.DataFrame:
        for encoding in ("utf-8-sig", "utf-16", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
            except UnicodeError:
                continue
        return pd.read_csv(path, dtype=str).fillna("")

    def _target_history_url(self, history_url: str) -> str:
        if self.customer_id and "ads.google.com/aw/changehistory" in history_url:
            return "https://ads.google.com/nav/selectaccount?dst=/aw/changehistory"
        return history_url

    def _fill_date_range(self, page: Any, start_at: datetime, end_at: datetime) -> None:
        start_selector = self.settings.GOOGLE_ADS_START_DATE_SELECTOR
        end_selector = self.settings.GOOGLE_ADS_END_DATE_SELECTOR
        if start_selector:
            page.locator(start_selector).first.fill(start_at.strftime("%Y-%m-%d"))
        if end_selector:
            page.locator(end_selector).first.fill(end_at.strftime("%Y-%m-%d"))
        if not start_selector and not end_selector:
            self.logger.warning(
                "Google Ads 날짜 selector가 없어 화면의 현재 날짜 범위로 다운로드합니다."
            )

    def _select_account_if_needed(self, page: Any) -> None:
        if "/nav/selectaccount" not in page.url:
            return

        customer_id = self.customer_id
        candidates = [customer_id]
        if len(customer_id) == 10 and customer_id.isdigit():
            candidates.insert(0, f"{customer_id[:3]}-{customer_id[3:6]}-{customer_id[6:]}")

        for candidate in [value for value in candidates if value]:
            locator = page.get_by_text(candidate, exact=True).first
            try:
                if locator.count():
                    self.logger.info("Google Ads 계정 선택: %s", candidate)
                    locator.click(timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=120000)
                    return
            except Exception:  # noqa: BLE001
                continue

        raise RuntimeError(
            "Google Ads 계정 선택 화면에서 GOOGLE_ADS_CUSTOMER_ID와 일치하는 계정을 찾지 못했습니다."
        )

    def _click_apply_or_search(self, page: Any) -> None:
        selector = self.settings.GOOGLE_ADS_SEARCH_BUTTON_SELECTOR
        if selector:
            page.locator(selector).first.click(timeout=30000)
            page.wait_for_load_state("networkidle", timeout=60000)
            return

        for pattern in (r"적용", r"Apply"):
            locator = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            try:
                if locator.count():
                    locator.click(timeout=10000)
                    page.wait_for_load_state("networkidle", timeout=60000)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _click_download(self, page: Any) -> None:
        selector = self.settings.GOOGLE_ADS_DOWNLOAD_BUTTON_SELECTOR
        if selector:
            page.locator(selector).first.click(timeout=30000)
            if self._click_download_format(page):
                return
            raise RuntimeError("구글SA 다운로드 포맷 메뉴를 찾지 못했습니다.")

        download_buttons = (
            page.locator("toolbelt-bar.primary-toolbelt material-button").filter(has_text="file_download").first,
            page.locator("material-button.trigger-button").filter(has_text="file_download").first,
            page.locator("toolbelt-bar material-button").filter(has_text="file_download").first,
            page.locator("material-button").filter(has_text="file_download").nth(1),
            page.locator("material-button").filter(has_text="file_download").first,
        )
        for icon_button in download_buttons:
            try:
                if not icon_button.count():
                    continue
                icon_button.click(timeout=30000)
                if self._click_download_format(page):
                    return
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                continue

        patterns = (r"다운로드", r"내보내기", r"Download", r"Export")
        for pattern in patterns:
            for finder in (
                lambda: page.get_by_role("button", name=re.compile(pattern, re.I)).first,
                lambda: page.get_by_label(re.compile(pattern, re.I)).first,
                lambda: page.get_by_title(re.compile(pattern, re.I)).first,
                lambda: page.get_by_text(re.compile(pattern, re.I)).first,
            ):
                try:
                    locator = finder()
                    if locator.count():
                        locator.click(timeout=30000)
                        if self._click_download_format(page):
                            return
                        raise RuntimeError("구글SA 다운로드 포맷 메뉴를 찾지 못했습니다.")
                except Exception:  # noqa: BLE001
                    continue

        raise RuntimeError(
            "구글SA 다운로드 버튼을 찾지 못했습니다. GOOGLE_ADS_DOWNLOAD_BUTTON_SELECTOR를 설정하세요."
        )

    @staticmethod
    def _click_download_format(page: Any) -> bool:
        menu_items = page.locator(
            'material-select-item, material-list-item, [role="menuitem"], [role="option"]'
        )
        for _ in range(20):
            for text in ("Excel .xlsx", ".xlsx", "Excel", "CSV", ".csv", ".tsv"):
                locator = menu_items.filter(has_text=text).first
                try:
                    if locator.count():
                        locator.click(timeout=30000)
                        return True
                except Exception:  # noqa: BLE001
                    continue
            page.wait_for_timeout(500)
        return False

    @staticmethod
    def _has_no_changes(page: Any) -> bool:
        markers = (
            "날짜 또는 필터와 일치하는 변경사항이 없습니다",
            "변경사항이 없습니다",
            "No changes match",
            "No changes found",
        )
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            body_text = ""
        return any(marker.lower() in body_text.lower() for marker in markers)

    @staticmethod
    def _dismiss_blocking_dialogs(page: Any) -> None:
        for pattern in (r"그대로 유지", r"나중에", r"닫기", r"Close", r"Dismiss"):
            locator = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            try:
                if locator.count() and locator.is_visible(timeout=1000):
                    locator.click(timeout=3000)
                    page.wait_for_timeout(500)
                    return
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _raise_if_logged_out(page: Any) -> None:
        url = page.url.lower()
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            body_text = ""

        if "accounts.google.com" in url or any(
            marker in body_text for marker in ("Google 계정으로 로그인", "Sign in", "로그인")
        ):
            raise GoogleAdsSessionExpiredError(
                "Google Ads 로그인 세션 만료 가능성: storage_state를 갱신하세요."
            )


def _cli() -> int:
    parser = argparse.ArgumentParser(description="구글SA Playwright 보조 명령")
    parser.add_argument("--login", action="store_true", help="브라우저 로그인 후 storage_state 저장")
    parser.add_argument("--download", action="store_true", help="오늘 변경이력 파일 다운로드 테스트")
    args = parser.parse_args()

    logger = get_logger("google_sa_browser_cli")
    collector = GoogleAdsBrowserChangeCollector(settings=default_settings, logger=logger)
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
