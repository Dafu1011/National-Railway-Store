from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class ObjectStorageConfig:
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    enabled: bool


def load_object_storage_config() -> ObjectStorageConfig:
    bucket = os.getenv("S3_BUCKET", "").strip()
    endpoint = os.getenv("S3_ENDPOINT", "").strip()
    return ObjectStorageConfig(
        endpoint=endpoint,
        bucket=bucket,
        region=os.getenv("S3_REGION", "").strip(),
        access_key=os.getenv("S3_ACCESS_KEY", "").strip(),
        secret_key=os.getenv("S3_SECRET_KEY", "").strip(),
        enabled=bool(endpoint and bucket),
    )


def material_object_key(*, user_id: str, upload_token: str, filename: str) -> str:
    safe_filename = Path(filename).name
    # Every object key starts with the account owner. S3/MinIO policies and DB ownership checks
    # can then enforce that one user never reads another user's material library.
    return f"users/{user_id}/materials/pending/{upload_token}/{safe_filename}"
