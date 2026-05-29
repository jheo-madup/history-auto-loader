from __future__ import annotations

from pathlib import Path
from typing import Any


def ensure_local_file(
    path: str,
    inline_content: str = "",
    secret_id: str = "",
    gcs_uri: str = "",
    project_id: str = "",
    logger: Any | None = None,
    label: str = "file",
) -> str:
    target = Path(path).expanduser()
    if target.exists():
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)

    if inline_content:
        target.write_text(inline_content, encoding="utf-8")
        _log(logger, "%s inline content를 로컬 파일로 저장했습니다: %s", label, target)
        return str(target)

    if secret_id:
        payload = _read_secret(secret_id=secret_id, project_id=project_id)
        target.write_bytes(payload)
        _log(logger, "%s Secret Manager 값을 로컬 파일로 저장했습니다: %s", label, target)
        return str(target)

    if gcs_uri:
        _download_gcs(gcs_uri=gcs_uri, target=target)
        _log(logger, "%s GCS 객체를 로컬 파일로 다운로드했습니다: %s", label, target)
        return str(target)

    return str(target)


def _read_secret(secret_id: str, project_id: str) -> bytes:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    if secret_id.startswith("projects/"):
        name = secret_id
        if "/versions/" not in name:
            name = f"{name}/versions/latest"
    else:
        if not project_id:
            raise ValueError("Secret Manager secret_id를 짧은 이름으로 쓸 때는 PROJECT_ID가 필요합니다.")
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data


def _download_gcs(gcs_uri: str, target: Path) -> None:
    from google.cloud import storage

    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"GCS URI 형식이 아닙니다: {gcs_uri}")
    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(str(target))


def _log(logger: Any | None, message: str, *args: Any) -> None:
    if logger is not None:
        logger.info(message, *args)
