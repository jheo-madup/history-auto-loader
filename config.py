"""Runtime configuration for SA history automation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _customer_id(value: str) -> str:
    return value.replace("-", "").strip()


@dataclass(frozen=True)
class Settings:
    SPREADSHEET_ID: str = _env(
        "SPREADSHEET_ID", "1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g"
    )
    RAW_WORKSHEET_NAME: str = _env("RAW_WORKSHEET_NAME", "히스토리자동화_Raw")
    SUMMARY_WORKSHEET_NAME: str = _env(
        "SUMMARY_WORKSHEET_NAME", "SA_히스토리적재_자동화"
    )
    TIMEZONE: str = _env("TIMEZONE", "Asia/Seoul")

    PROJECT_ID: str = _env("PROJECT_ID", "madup-samsungsec")
    REGION: str = _env("REGION", "asia-northeast3")
    RUN_SERVICE_ACCOUNT: str = _env(
        "RUN_SERVICE_ACCOUNT",
        "mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com",
    )

    GOOGLE_ADS_CUSTOMER_ID: str = _customer_id(_env("GOOGLE_ADS_CUSTOMER_ID"))
    GOOGLE_ADS_CUSTOMER_IDS: str = _env("GOOGLE_ADS_CUSTOMER_IDS")
    GOOGLE_AC_CUSTOMER_IDS: str = _env("GOOGLE_AC_CUSTOMER_IDS")
    GOOGLE_ADS_LOGIN_CUSTOMER_ID: str = _customer_id(
        _env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    )
    GOOGLE_ADS_CONFIG_PATH: str = _env(
        "GOOGLE_ADS_CONFIG_PATH", str(BASE_DIR / "secrets" / "google-ads.yaml")
    )
    GOOGLE_ADS_YAML_CONTENT: str = _env("GOOGLE_ADS_YAML_CONTENT")
    GOOGLE_ADS_CONFIG_SECRET_ID: str = _env("GOOGLE_ADS_CONFIG_SECRET_ID")
    GOOGLE_ADS_CONFIG_GCS_URI: str = _env("GOOGLE_ADS_CONFIG_GCS_URI")
    GOOGLE_SA_COLLECTION_MODE: str = _env("GOOGLE_SA_COLLECTION_MODE", "api")
    GOOGLE_ADS_HISTORY_URL: str = _env("GOOGLE_ADS_HISTORY_URL")
    GOOGLE_ADS_HISTORY_FILE_PATH: str = _env("GOOGLE_ADS_HISTORY_FILE_PATH")
    GOOGLE_ADS_STORAGE_STATE_PATH: str = _env(
        "GOOGLE_ADS_STORAGE_STATE_PATH",
        str(BASE_DIR / "secrets" / "google_ads_storage_state.json"),
    )
    GOOGLE_ADS_STORAGE_STATE_JSON: str = _env("GOOGLE_ADS_STORAGE_STATE_JSON")
    GOOGLE_ADS_STORAGE_STATE_SECRET_ID: str = _env("GOOGLE_ADS_STORAGE_STATE_SECRET_ID")
    GOOGLE_ADS_STORAGE_STATE_GCS_URI: str = _env("GOOGLE_ADS_STORAGE_STATE_GCS_URI")
    GOOGLE_ADS_DOWNLOAD_DIR: str = _env(
        "GOOGLE_ADS_DOWNLOAD_DIR", str(BASE_DIR / "downloads")
    )
    GOOGLE_ADS_HEADLESS: bool = _env_bool("GOOGLE_ADS_HEADLESS", True)
    GOOGLE_ADS_ALLOW_INTERACTIVE_LOGIN: bool = _env_bool(
        "GOOGLE_ADS_ALLOW_INTERACTIVE_LOGIN", False
    )
    GOOGLE_ADS_START_DATE_SELECTOR: str = _env("GOOGLE_ADS_START_DATE_SELECTOR")
    GOOGLE_ADS_END_DATE_SELECTOR: str = _env("GOOGLE_ADS_END_DATE_SELECTOR")
    GOOGLE_ADS_SEARCH_BUTTON_SELECTOR: str = _env("GOOGLE_ADS_SEARCH_BUTTON_SELECTOR")
    GOOGLE_ADS_DOWNLOAD_BUTTON_SELECTOR: str = _env("GOOGLE_ADS_DOWNLOAD_BUTTON_SELECTOR")

    NAVER_LOGIN_STATE_PATH: str = _env(
        "NAVER_LOGIN_STATE_PATH", str(BASE_DIR / "secrets" / "naver_storage_state.json")
    )
    NAVER_STORAGE_STATE_PATH: str = _env(
        "NAVER_STORAGE_STATE_PATH", NAVER_LOGIN_STATE_PATH
    )
    NAVER_STORAGE_STATE_JSON: str = _env("NAVER_STORAGE_STATE_JSON")
    NAVER_STORAGE_STATE_SECRET_ID: str = _env("NAVER_STORAGE_STATE_SECRET_ID")
    NAVER_STORAGE_STATE_GCS_URI: str = _env("NAVER_STORAGE_STATE_GCS_URI")
    NAVER_HISTORY_URL: str = _env("NAVER_HISTORY_URL")
    NAVER_HISTORY_XLSX_PATH: str = _env("NAVER_HISTORY_XLSX_PATH")
    NAVER_DOWNLOAD_DIR: str = _env(
        "NAVER_DOWNLOAD_DIR", str(BASE_DIR / "downloads")
    )
    NAVER_HEADLESS: bool = _env_bool("NAVER_HEADLESS", True)
    NAVER_ALLOW_INTERACTIVE_LOGIN: bool = _env_bool(
        "NAVER_ALLOW_INTERACTIVE_LOGIN", False
    )
    NAVER_START_DATE_SELECTOR: str = _env("NAVER_START_DATE_SELECTOR")
    NAVER_END_DATE_SELECTOR: str = _env("NAVER_END_DATE_SELECTOR")
    NAVER_SEARCH_BUTTON_SELECTOR: str = _env("NAVER_SEARCH_BUTTON_SELECTOR")
    NAVER_DOWNLOAD_BUTTON_SELECTOR: str = _env("NAVER_DOWNLOAD_BUTTON_SELECTOR")

    META_HISTORY_URL: str = _env("META_HISTORY_URL")
    META_HISTORY_FILE_PATH: str = _env("META_HISTORY_FILE_PATH")
    META_STORAGE_STATE_PATH: str = _env(
        "META_STORAGE_STATE_PATH", str(BASE_DIR / "secrets" / "meta_storage_state.json")
    )
    META_STORAGE_STATE_JSON: str = _env("META_STORAGE_STATE_JSON")
    META_STORAGE_STATE_SECRET_ID: str = _env("META_STORAGE_STATE_SECRET_ID")
    META_STORAGE_STATE_GCS_URI: str = _env("META_STORAGE_STATE_GCS_URI")
    META_DOWNLOAD_DIR: str = _env("META_DOWNLOAD_DIR", str(BASE_DIR / "downloads"))
    META_HEADLESS: bool = _env_bool("META_HEADLESS", True)
    META_ALLOW_INTERACTIVE_LOGIN: bool = _env_bool("META_ALLOW_INTERACTIVE_LOGIN", False)
    META_START_DATE_SELECTOR: str = _env("META_START_DATE_SELECTOR")
    META_END_DATE_SELECTOR: str = _env("META_END_DATE_SELECTOR")
    META_SEARCH_BUTTON_SELECTOR: str = _env("META_SEARCH_BUTTON_SELECTOR")
    META_DOWNLOAD_BUTTON_SELECTOR: str = _env("META_DOWNLOAD_BUTTON_SELECTOR")

    AD_INDEX_ENABLED: bool = _env_bool("AD_INDEX_ENABLED", True)
    AD_INDEX_SPREADSHEET_ID: str = _env(
        "AD_INDEX_SPREADSHEET_ID", "12w86uqNNzzHjR0ycsNTPuJZ0VH6a8VL9ky2Cm6WwDGg"
    )
    AD_INDEX_WORKSHEET_NAME: str = _env("AD_INDEX_WORKSHEET_NAME", "광고 인덱스")
    AD_INDEX_HEADER_ROW: str = _env("AD_INDEX_HEADER_ROW", "5")
    AD_INDEX_CAMPAIGN_COLUMN: str = _env("AD_INDEX_CAMPAIGN_COLUMN", "Campaign")
    AD_INDEX_AD_GROUP_COLUMN: str = _env("AD_INDEX_AD_GROUP_COLUMN", "Ad Group")
    AD_INDEX_MEDIA_COLUMN: str = _env("AD_INDEX_MEDIA_COLUMN", "rd[dim_media]")
    AD_INDEX_SUMMARY_COLUMN: str = _env("AD_INDEX_SUMMARY_COLUMN", "rd[dim_cat1_campaign]")
    AD_INDEX_SUMMARY_ENTITY_MEDIA: str = _env("AD_INDEX_SUMMARY_ENTITY_MEDIA", "메타")

    AUTO_BID_SHEET_ENABLED: bool = _env_bool("AUTO_BID_SHEET_ENABLED", True)
    AUTO_BID_SPREADSHEET_ID: str = _env(
        "AUTO_BID_SPREADSHEET_ID", "1k4uQxx6n0k1Tv3IB34MQc6i35KAoE6VPzG5Fc1UEMN4"
    )
    AUTO_BID_WORKSHEET_NAME: str = _env("AUTO_BID_WORKSHEET_NAME")
    AUTO_BID_WORKSHEET_GID: str = _env("AUTO_BID_WORKSHEET_GID", "2077662868")
    AUTO_BID_HEADER_ROW: str = _env("AUTO_BID_HEADER_ROW", "1")
    AUTO_BID_KEYWORD_COLUMN: str = _env("AUTO_BID_KEYWORD_COLUMN", "키워드")
    AUTO_BID_TARGET_RANK_COLUMN: str = _env("AUTO_BID_TARGET_RANK_COLUMN", "목표순위")
    AUTO_BID_CAMPAIGN_COLUMN: str = _env("AUTO_BID_CAMPAIGN_COLUMN", "Campaign")
    AUTO_BID_AD_GROUP_COLUMN: str = _env("AUTO_BID_AD_GROUP_COLUMN", "Ad Group")
    AUTO_BID_MEDIA_COLUMN: str = _env("AUTO_BID_MEDIA_COLUMN")
    AUTO_BID_STATE_WORKSHEET_NAME: str = _env(
        "AUTO_BID_STATE_WORKSHEET_NAME", "_자동입찰_snapshot_state"
    )
    AUTO_BID_FALLBACK_MEDIA: str = _env("AUTO_BID_FALLBACK_MEDIA", "네이버SA")

    RUN_MODE: str = _env("RUN_MODE", "local")
    ENABLE_GOOGLE_SA: bool = _env_bool("ENABLE_GOOGLE_SA", True)
    ENABLE_NAVER_SA: bool = _env_bool("ENABLE_NAVER_SA", True)
    ENABLE_META: bool = _env_bool("ENABLE_META", False)


settings = Settings()
