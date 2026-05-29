# SA 변경기록 자동화

구글SA / 네이버SA 변경기록을 당일 누적 기준으로 수집해 Google Sheets에 적재하는 Python 자동화입니다.

- Raw 탭: `히스토리자동화_Raw`
- 요약 탭: `SA_히스토리적재_자동화`
- 스프레드시트 ID: `1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g`
- 실행 방식: Cloud Run Job + Cloud Scheduler
- 실행 시간: 매일 `12:00`, `18:00`, `23:00` Asia/Seoul

## 구조

```text
.
├── main.py
├── config.py
├── requirements.txt
├── Dockerfile
├── collectors/
│   ├── google_ads_browser_change.py
│   ├── google_ads_change.py
│   └── naver_sa_change.py
├── processors/
│   ├── normalizer.py
│   ├── filters.py
│   └── summarizer.py
├── writers/
│   └── sheet_writer.py
└── utils/
    ├── datetime_utils.py
    ├── hash_utils.py
    ├── logger.py
    └── state_loader.py
```

## 동작 방식

1. Asia/Seoul 기준 현재 시각을 계산합니다.
2. 실행 당일 `00:00:00`부터 실행 시점까지 조회합니다.
3. 구글SA는 `GOOGLE_SA_COLLECTION_MODE=browser`이면 Playwright로 변경 이력 화면에서 파일을 다운로드합니다.
4. `GOOGLE_SA_COLLECTION_MODE=api`이면 Google Ads API `change_event`를 조회합니다.
5. 네이버SA는 Playwright로 이력관리 화면에서 xlsx를 다운로드합니다.
6. 공통 Raw 컬럼으로 normalize합니다.
7. 단순 일예산 변경, 시스템/API 로그, 검수/심사 상태, 이름 수정, 의미 없는 저장 로그를 제외합니다.
8. 일예산이 미설정/0원에서 새로 설정된 경우와 콘텐츠 매체 전용입찰가 변경은 특이 케이스로 유지합니다.
9. 광고 인덱스의 캠페인명/광고그룹명 기준으로 매체명을 보정합니다.
10. 자동입찰시트의 `자동입찰_변경로그` 탭에서 목표순위 변경 로그를 읽어 Raw/요약에 추가합니다.
11. `row_hash`로 중복을 제거하고 Raw 탭은 최근 7일치만 유지합니다.
12. Raw 기준으로 일자/매체별 요약을 다시 만들고 요약 탭 셀을 덮어씁니다.
13. Slack 알림이 활성화되어 있으면 요약 내용을 지정 채널로 발송합니다.

## 로컬 설정

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

`.env`에 최소값을 채웁니다.

```env
GOOGLE_ADS_CUSTOMER_ID=1234567890
GOOGLE_ADS_CUSTOMER_IDS=1234567890,5296599507
GOOGLE_AC_CUSTOMER_IDS=
GOOGLE_ADS_LOGIN_CUSTOMER_ID=
GOOGLE_ADS_CONFIG_PATH=./secrets/google-ads.yaml
GOOGLE_SA_COLLECTION_MODE=browser
GOOGLE_ADS_HISTORY_URL=https://ads.google.com/aw/changehistory
GOOGLE_ADS_STORAGE_STATE_PATH=./secrets/google_ads_storage_state.json

NAVER_HISTORY_URL=https://...
NAVER_STORAGE_STATE_PATH=./secrets/naver_storage_state.json
NAVER_START_DATE_SELECTOR=
NAVER_END_DATE_SELECTOR=
NAVER_SEARCH_BUTTON_SELECTOR=
NAVER_DOWNLOAD_BUTTON_SELECTOR=

AUTO_BID_SHEET_ENABLED=true
AUTO_BID_SPREADSHEET_ID=1k4uQxx6n0k1Tv3IB34MQc6i35KAoE6VPzG5Fc1UEMN4
AUTO_BID_WORKSHEET_GID=2077662868
AUTO_BID_LOG_WORKSHEET_NAME=자동입찰_변경로그
AUTO_BID_LOG_LOOKBACK_DAYS=7

SLACK_NOTIFICATIONS_ENABLED=true
SLACK_CHANNEL_ID=C04JCCUDR1R
SLACK_BOT_TOKEN=
```

Google Sheets 로컬 인증은 아래 중 하나를 사용합니다.

```powershell
gcloud.cmd auth application-default login
```

또는 서비스 계정 impersonation을 사용합니다.

```powershell
gcloud.cmd auth application-default login --impersonate-service-account=mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com
```

Windows PowerShell에서 `gcloud.ps1` 실행 정책 오류가 나면 `gcloud.cmd`를 사용합니다.

스프레드시트는 실행 서비스 계정 `mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com`에 편집 권한으로 공유되어 있어야 합니다.

## 로컬 테스트

기본 실행:

```powershell
python main.py
```

특정 일자:

```powershell
python main.py --date 2026-05-27
```

특정 범위:

```powershell
python main.py --start "2026-05-27 00:00:00" --end "2026-05-27 18:00:00"
```

매체별 테스트:

```powershell
python main.py --media google
python main.py --media naver
```

단위 테스트:

```powershell
python -m unittest tests.test_history_logic
```

구글SA 파일 파싱만 먼저 테스트:

```powershell
$env:GOOGLE_ADS_HISTORY_FILE_PATH="C:\path\to\google_ads_history.xlsx"
python main.py --media google
```

네이버 xlsx 파싱만 먼저 테스트:

```powershell
$env:NAVER_HISTORY_XLSX_PATH="C:\path\to\naver_history.xlsx"
python main.py --media naver
```

## 구글SA 브라우저 로그인 세션

현재 `.env`는 Google Ads API 승인 전 테스트를 위해 아래처럼 브라우저 모드가 기본입니다.

```env
GOOGLE_SA_COLLECTION_MODE=browser
GOOGLE_ADS_HISTORY_URL=https://ads.google.com/aw/changehistory
GOOGLE_ADS_STORAGE_STATE_PATH=./secrets/google_ads_storage_state.json
```

최초 1회 로컬에서 Google Ads 로그인 상태를 저장합니다.

```powershell
$env:GOOGLE_ADS_ALLOW_INTERACTIVE_LOGIN="true"
python -m collectors.google_ads_browser_change --login
```

기본 저장 위치는 `./secrets/google_ads_storage_state.json`입니다. 이 파일은 이미지에 포함하지 말고 Secret Manager 또는 GCS로 공급합니다.

Google Ads 변경 이력 화면의 날짜 입력/적용/다운로드 버튼은 화면 구성에 따라 selector가 다를 수 있습니다. 자동 클릭이 실패하면 `.env`에 아래 값을 지정합니다.

```env
GOOGLE_ADS_START_DATE_SELECTOR=
GOOGLE_ADS_END_DATE_SELECTOR=
GOOGLE_ADS_SEARCH_BUTTON_SELECTOR=
GOOGLE_ADS_DOWNLOAD_BUTTON_SELECTOR=
```

세션이 만료되면 로그에 `Google Ads 로그인 세션 만료 가능성`이 출력됩니다.

API 승인 후 `change_event` 방식으로 되돌리려면:

```env
GOOGLE_SA_COLLECTION_MODE=api
```

Google Ads는 여러 계정을 쉼표로 지정할 수 있습니다. 앱 캠페인/실적최대화 캠페인은 `구글AC`로, 그 외 검색 캠페인은 `구글SA`로 적재합니다. 특정 계정 전체를 AC로 취급해야 할 때만 `GOOGLE_AC_CUSTOMER_IDS`에 추가합니다.

```env
GOOGLE_ADS_CUSTOMER_IDS=385-327-7410,529-659-9507
GOOGLE_AC_CUSTOMER_IDS=
```

## 광고 인덱스 매체 라우팅

캠페인명이 광고 인덱스에 있으면 인덱스의 매체값을 우선 사용합니다. 캠페인명 매칭이 실패하면 광고그룹명을 인덱스의 `Ad Group` 컬럼에서 찾아 매체를 보정합니다. 현재 광고 인덱스에서 실제 매체명은 `rd[dim_media]`에 있으므로 기본값은 이 컬럼입니다. `rd[dim_cat1_campaign]`처럼 다른 컬럼으로 요약 컬럼을 나누고 싶으면 `AD_INDEX_MEDIA_COLUMN`만 바꾸면 됩니다.

```env
AD_INDEX_ENABLED=true
AD_INDEX_SPREADSHEET_ID=12w86uqNNzzHjR0ycsNTPuJZ0VH6a8VL9ky2Cm6WwDGg
AD_INDEX_WORKSHEET_NAME=광고 인덱스
AD_INDEX_WORKSHEET_GID=2063584549
AD_INDEX_HEADER_ROW=5
AD_INDEX_CAMPAIGN_COLUMN=Campaign
AD_INDEX_AD_GROUP_COLUMN=Ad Group
AD_INDEX_MEDIA_COLUMN=rd[dim_media]
AD_INDEX_EXTRA_WORKSHEET_NAMES=[DA] URL 생성;[BS, 신제품검색] URL 생성;[SA,파컨] URL 생성
AD_INDEX_EXTRA_HEADER_ROW=7
AD_INDEX_EXTRA_CAMPAIGN_COLUMNS=캠페인 (Campaign);캠페인명;Campaign
AD_INDEX_EXTRA_AD_GROUP_COLUMNS=그룹 (Ad Group);그룹명;Ad Group
AD_INDEX_EXTRA_MEDIA_COLUMNS=매체;rd[dim_media]
```

인덱스 값 `네이버SA_파워콘텐츠`는 히스토리 요약 탭의 `네이버 파워컨텐츠` 컬럼으로 자동 변환합니다.
캠페인명뿐 아니라 광고그룹명도 인덱스의 `Ad Group` 컬럼에서 찾아 매체를 보정합니다.
인덱스에서 캠페인명/광고그룹명을 모두 찾지 못하면 기존 수집 매체값을 사용하고 로그에 `인덱스 매칭 실패`를 남깁니다.
`광고 인덱스` 탭의 수식 반영이 늦거나 일부 URL 생성 탭이 누락되어도 `[DA] URL 생성`, `[BS, 신제품검색] URL 생성`, `[SA,파컨] URL 생성` 탭을 보조 인덱스로 함께 읽어 매체를 보정합니다. 여러 보조 탭을 넣어야 하면 `AD_INDEX_EXTRA_WORKSHEET_NAMES`에 세미콜론(`;`)으로 구분해 지정합니다.

메타는 여러 상품/캠페인 분류가 같은 매체 안에서 함께 운영되므로 요약 제목을 캠페인명이 아니라 광고 인덱스의 `rd[dim_cat1_campaign]` 값으로 표시합니다.

```text
[국내주식] 변경 내용
[연금] 변경 내용
```

## 네이버SA 로그인 세션

최초 1회 로컬에서 로그인 상태를 저장합니다.

```powershell
$env:NAVER_ALLOW_INTERACTIVE_LOGIN="true"
python -m collectors.naver_sa_change --login
```

기본 저장 위치는 `./secrets/naver_storage_state.json`입니다. 이 파일은 이미지에 포함하지 말고 Secret Manager 또는 GCS로 공급합니다.

네이버 이력관리 화면의 날짜 입력/조회/다운로드 버튼은 화면 구성에 따라 selector가 다를 수 있습니다. 자동 클릭이 실패하면 `.env`에 아래 값을 지정합니다.

```env
NAVER_START_DATE_SELECTOR=input[name="startDate"]
NAVER_END_DATE_SELECTOR=input[name="endDate"]
NAVER_SEARCH_BUTTON_SELECTOR=button:has-text("조회")
NAVER_DOWNLOAD_BUTTON_SELECTOR=button:has-text("엑셀 다운로드")
```

세션이 만료되면 로그에 `네이버 로그인 세션 만료 가능성`이 출력됩니다.

네이버 변경자 중 `dreamful7:naver(API)`는 Raw 적재와 요약에서 제외합니다.

네이버 로그 중 캠페인/그룹/소재/키워드가 비어 있거나 `소재 검수`, `키워드 검토`, `검토 상태`, `심사` 관련 로그는 Raw 탭에 연한 노란색으로 표시합니다. 검수 통과 여부처럼 캠페인/매체 인덱스 매칭이 어려운 로그를 나중에 확인하기 위한 표시입니다.

요약 히스토리 탭에는 엔티티가 `미분류`인 로그를 넣지 않습니다. Raw에서 색상 표시된 행은 원본 확인용으로만 남깁니다.

구글/네이버 모두 요약은 `변경일시`를 파싱한 실제 변경일 기준으로 조회기간 안의 로그만 사용합니다. 날짜를 파싱하지 못한 행은 Raw 적재 대상에서 제외합니다.

tCPA/목표 CPA 변경은 요약에 이전값과 변경값을 함께 표시합니다. 예: `₩13,500 -> ₩11,000 하향`.

구글 요약은 단어 하나만으로 분류하지 않고 변경 문맥을 함께 봅니다. 예를 들어 `제외 데이터 세그먼트`는 키워드 제외가 아니라 `제외 데이터 세그먼트 추가`로 정리합니다.

일예산 변경은 기본적으로 Raw/요약에서 제외합니다. 단, 미설정/빈값/null/0원에서 새 예산이 설정된 경우는 `[캠페인명] 일예산 신규 설정: 100,000원` 형식으로 남깁니다.

소재 변경은 동일 일자/매체/캠페인/광고그룹 기준으로 3건 이상이면 소재명을 나열하지 않고 `[광고그룹명] 소재 5건 변경`처럼 건수 중심으로 요약합니다.

## 자동입찰시트 변경 수집

자동입찰시트는 Google Sheets UI의 셀 수정 기록을 직접 조회하지 않습니다. 자동입찰 스프레드시트에 Apps Script `onEdit(e)`를 설치해 `목표 순위`/`목표순위` 변경을 `자동입찰_변경로그` 탭에 남기고, 히스토리 자동화는 이 로그 탭을 Google Sheets API로 읽습니다.

```env
AUTO_BID_SHEET_ENABLED=true
AUTO_BID_SPREADSHEET_ID=1k4uQxx6n0k1Tv3IB34MQc6i35KAoE6VPzG5Fc1UEMN4
AUTO_BID_WORKSHEET_NAME=
AUTO_BID_WORKSHEET_GID=2077662868
AUTO_BID_HEADER_ROW=1
AUTO_BID_KEYWORD_COLUMN=키워드
AUTO_BID_TARGET_RANK_COLUMN=목표순위
AUTO_BID_CAMPAIGN_COLUMN=Campaign
AUTO_BID_AD_GROUP_COLUMN=Ad Group
AUTO_BID_MEDIA_COLUMN=
AUTO_BID_LOG_WORKSHEET_NAME=자동입찰_변경로그
AUTO_BID_LOG_LOOKBACK_DAYS=7
AUTO_BID_FALLBACK_MEDIA=네이버SA
```

자동입찰 스프레드시트의 Apps Script 편집기에 [apps_script/auto_bid_on_edit.gs](apps_script/auto_bid_on_edit.gs) 내용을 추가합니다. 최초 설치 후 `initializeAutoBidTargetRankSnapshot()`을 1회 수동 실행해 현재 목표순위를 기준값으로 저장하면, 이후 단일 수정과 대량 붙여넣기 모두 행 단위로 로그가 남습니다.

`자동입찰_변경로그` 탭 컬럼:

```text
변경일시, 변경일자, 변경자, 시트명, 행번호, 키워드, 캠페인명, 캠페인 ID,
광고그룹명, 광고그룹 ID, 키워드 ID, 디바이스, 변경필드, 이전값, 변경값, raw_text
```

요약 예시:

```text
주식계좌개설 목표순위 4순위 → 3순위 변경
ISA 목표순위 3순위로 신규 설정
[m_일반] 목표순위 변경 키워드 5건
```

Raw에는 `변경유형=자동입찰 목표순위 변경`, `변경작업=목표순위 변경`, `변경필드=목표순위`, `변경레벨=키워드`로 적재합니다. `row_hash`는 `source=auto_bid_sheet`, 변경일자, 키워드 ID, 키워드, 캠페인명, 광고그룹명, 이전값, 변경값, 변경필드를 기준으로 생성합니다.

## Slack 요약 알림

요약 탭 적재가 정상 완료되면 Slack Bot으로 이번 실행에서 실제 신규 반영된 수동 변경 내역의 매체별 건수를 발송할 수 있습니다. 토큰은 코드나 GitHub에 올리지 말고 Secret Manager 또는 Cloud Run Secret env로만 주입합니다.

```env
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C04JCCUDR1R
SLACK_MESSAGE_MAX_CHARS=35000
SLACK_API_TIMEOUT_SECONDS=10
```

Slack App에는 최소 `chat:write` 권한이 필요하고, Bot이 `C04JCCUDR1R` 채널에 초대되어 있어야 합니다. 토큰이 없거나 채널 ID가 비어 있으면 자동화는 실패하지 않고 Slack 발송만 건너뜁니다.

Slack 메시지 형식:

```text
*<https://docs.google.com/spreadsheets/d/1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g/edit?gid=1211091820#gid=1211091820|SA / AC 히스토리 자동 적재 완료>* - :red_circle: 수동 변경 내역 기준

네이버SA: 0건
구글SA: 0건
구글AC: 0건
네이버 파워컨텐츠: 0건
브랜드검색: 0건
```

## 메타 로그인 세션

메타는 변경 이력 화면에서 xlsx/csv를 다운로드하는 Playwright 하네스로 동작합니다. 먼저 `.env`에 변경 이력 화면 URL을 넣고 활성화합니다.

```env
ENABLE_META=true
META_HISTORY_URL=https://...
META_STORAGE_STATE_PATH=./secrets/meta_storage_state.json
```

최초 1회 로컬에서 로그인 상태를 저장합니다.

```powershell
$env:META_ALLOW_INTERACTIVE_LOGIN="true"
python -m collectors.meta_change --login
```

다운로드 버튼이나 날짜 입력을 자동으로 못 찾으면 아래 selector를 `.env`에 지정합니다.

```env
META_START_DATE_SELECTOR=
META_END_DATE_SELECTOR=
META_SEARCH_BUTTON_SELECTOR=
META_DOWNLOAD_BUTTON_SELECTOR=
```

로컬 파일로 먼저 테스트할 수도 있습니다.

```env
META_HISTORY_FILE_PATH=./downloads/meta_history_sample.xlsx
```

```powershell
python main.py --media meta
```

## Secret Manager

Google Ads 설정 파일:

```bash
gcloud secrets create google-ads-yaml --replication-policy=automatic --project=madup-samsungsec
gcloud secrets versions add google-ads-yaml --data-file=./secrets/google-ads.yaml --project=madup-samsungsec
```

네이버 storage_state:

```bash
gcloud secrets create naver-storage-state --replication-policy=automatic --project=madup-samsungsec
gcloud secrets versions add naver-storage-state --data-file=./secrets/naver_storage_state.json --project=madup-samsungsec
```

Google Ads browser storage_state:

```bash
gcloud secrets create google-ads-storage-state --replication-policy=automatic --project=madup-samsungsec
gcloud secrets versions add google-ads-storage-state --data-file=./secrets/google_ads_storage_state.json --project=madup-samsungsec
```

Slack Bot token:

```bash
gcloud secrets create slack-bot-token --replication-policy=automatic --project=madup-samsungsec
printf '%s' 'xoxb-...' | gcloud secrets versions add slack-bot-token --data-file=- --project=madup-samsungsec
```

Secret 접근 권한:

```bash
gcloud secrets add-iam-policy-binding google-ads-yaml \
  --project=madup-samsungsec \
  --member="serviceAccount:mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding naver-storage-state \
  --project=madup-samsungsec \
  --member="serviceAccount:mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding google-ads-storage-state \
  --project=madup-samsungsec \
  --member="serviceAccount:mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding slack-bot-token \
  --project=madup-samsungsec \
  --member="serviceAccount:mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Cloud Run Job에는 Secret payload를 환경변수로 주입하는 방식을 권장합니다.

- `GOOGLE_ADS_YAML_CONTENT=google-ads-yaml:latest`
- `GOOGLE_ADS_STORAGE_STATE_JSON=google-ads-storage-state:latest`
- `NAVER_STORAGE_STATE_JSON=naver-storage-state:latest`
- `SLACK_BOT_TOKEN=slack-bot-token:latest`

대안으로 런타임에서 직접 Secret Manager/GCS를 읽도록 `GOOGLE_ADS_CONFIG_SECRET_ID`, `GOOGLE_ADS_STORAGE_STATE_SECRET_ID`, `NAVER_STORAGE_STATE_SECRET_ID`, `GOOGLE_ADS_CONFIG_GCS_URI`, `GOOGLE_ADS_STORAGE_STATE_GCS_URI`, `NAVER_STORAGE_STATE_GCS_URI`를 사용할 수 있습니다.

## Cloud Run Job 배포

Cloud Shell 기준 예시입니다.

```bash
PROJECT_ID=madup-samsungsec
REGION=asia-northeast3
JOB_NAME=sa-history-automation
REPO=sa-history
SERVICE_ACCOUNT=mkt14-automation-runner@madup-samsungsec.iam.gserviceaccount.com
IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${JOB_NAME}:latest

gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sheets.googleapis.com \
  storage.googleapis.com \
  --project=${PROJECT_ID}

gcloud artifacts repositories create ${REPO} \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID}

gcloud builds submit --tag ${IMAGE} --project=${PROJECT_ID}

gcloud run jobs create ${JOB_NAME} \
  --image=${IMAGE} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --service-account=${SERVICE_ACCOUNT} \
  --memory=2Gi \
  --cpu=2 \
  --task-timeout=1800 \
  --set-env-vars=RUN_MODE=cloudrun,PROJECT_ID=${PROJECT_ID},REGION=${REGION},TIMEZONE=Asia/Seoul,SPREADSHEET_ID=1-pcaJCyUc3_DQPuNNZgDvc433Cdo2DbrwFsxLbxv95g,RAW_WORKSHEET_NAME=히스토리자동화_Raw,SUMMARY_WORKSHEET_NAME=SA_히스토리적재_자동화,GOOGLE_SA_COLLECTION_MODE=browser,GOOGLE_ADS_CUSTOMER_ID=YOUR_CUSTOMER_ID,GOOGLE_ADS_LOGIN_CUSTOMER_ID=YOUR_LOGIN_CUSTOMER_ID,GOOGLE_ADS_HISTORY_URL=https://ads.google.com/aw/changehistory,NAVER_HISTORY_URL=YOUR_NAVER_HISTORY_URL,AD_INDEX_AD_GROUP_COLUMN="Ad Group",AUTO_BID_SHEET_ENABLED=true,AUTO_BID_SPREADSHEET_ID=1k4uQxx6n0k1Tv3IB34MQc6i35KAoE6VPzG5Fc1UEMN4,AUTO_BID_WORKSHEET_GID=2077662868,AUTO_BID_LOG_WORKSHEET_NAME=자동입찰_변경로그,AUTO_BID_LOG_LOOKBACK_DAYS=7,SLACK_NOTIFICATIONS_ENABLED=true,SLACK_CHANNEL_ID=C04JCCUDR1R \
  --set-secrets=GOOGLE_ADS_YAML_CONTENT=google-ads-yaml:latest,GOOGLE_ADS_STORAGE_STATE_JSON=google-ads-storage-state:latest,NAVER_STORAGE_STATE_JSON=naver-storage-state:latest,SLACK_BOT_TOKEN=slack-bot-token:latest
```

수동 실행:

```bash
gcloud run jobs execute ${JOB_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --wait
```

기존 Job을 새 이미지로 갱신:

```bash
gcloud run jobs update ${JOB_NAME} \
  --image=${IMAGE} \
  --region=${REGION} \
  --project=${PROJECT_ID}
```

## Cloud Scheduler

Scheduler가 Cloud Run Job을 실행할 수 있도록 권한을 부여합니다.

```bash
gcloud run jobs add-iam-policy-binding ${JOB_NAME} \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker"
```

스케줄 생성:

```bash
gcloud scheduler jobs create http sa-history-automation-schedule \
  --location=${REGION} \
  --project=${PROJECT_ID} \
  --schedule="0 12,18,23 * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run" \
  --http-method=POST \
  --oauth-service-account-email=${SERVICE_ACCOUNT} \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
```

수동 트리거:

```bash
gcloud scheduler jobs run sa-history-automation-schedule \
  --location=${REGION} \
  --project=${PROJECT_ID}
```

## 시트 조건

Raw 탭 첫 행은 코드가 비어 있을 때 자동 생성합니다. 기존 헤더가 있으면 아래 컬럼이 모두 있어야 합니다. 실행 때마다 최근 7일 범위 밖의 Raw 행은 제거되고, 신규 행이 row_hash 기준으로 merge됩니다.

```text
수집일시, 조회시작일시, 조회종료일시, 일자, 매체, 계정ID, 계정명, 변경일시, 변경자,
캠페인명, 광고그룹명, 소재명, 키워드명, 변경레벨, 변경유형, 변경작업, 변경필드,
이전값, 변경값, 변경내용, 원본리소스명, raw_text, row_hash
```

요약 탭은 2행을 매체 헤더로 사용합니다. 기본 매체는 아래처럼 두고, 인덱스 라우팅으로 새 매체가 나오면 코드가 오른쪽에 컬럼을 자동 추가합니다.

```text
A열: 일자
2행: 네이버SA, 구글SA, 구글AC
```

자동입찰 스프레드시트에는 Apps Script가 `자동입찰_변경로그` 탭과 hidden 스냅샷 탭 `_자동입찰_목표순위_snapshot`을 생성합니다.

## 참고 공식 문서

- Google Ads API Change Event: https://developers.google.com/google-ads/api/docs/change-event
- Cloud Run Jobs 실행: https://cloud.google.com/run/docs/execute/jobs
- `gcloud run jobs create`: https://cloud.google.com/sdk/gcloud/reference/run/jobs/create
- `gcloud scheduler jobs create http`: https://cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http
