"""MinIO / S3-compatible storage for incident clips."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "incidents"
DEFAULT_PREFIX = "incidents/ingest/"
DEFAULT_REGION = "us-east-1"
DEFAULT_PRESIGN_EXPIRE_S = 7 * 24 * 3600


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def utc_offset_hours() -> int:
    return _env_int("NEXUS_DS_UTC_OFFSET_HOURS", 5)


class MinioConfig:
    def __init__(self) -> None:
        self.endpoint_url = _env("NEXUS_DS_MINIO_ENDPOINT_URL")
        self.access_key = _env("NEXUS_DS_MINIO_ACCESS_KEY")
        self.secret_key = _env("NEXUS_DS_MINIO_SECRET_KEY")
        self.region = _env("NEXUS_DS_MINIO_REGION", DEFAULT_REGION) or DEFAULT_REGION
        self.bucket = _env("NEXUS_DS_MINIO_BUCKET", DEFAULT_BUCKET) or DEFAULT_BUCKET
        prefix = _env("NEXUS_DS_MINIO_KEY_PREFIX", DEFAULT_PREFIX) or DEFAULT_PREFIX
        self.key_prefix = prefix.strip("/") + "/"
        self.public_url = _env("NEXUS_DS_MINIO_PUBLIC_URL").rstrip("/")
        self.presign_expire_s = max(
            60, _env_int("NEXUS_DS_MINIO_PRESIGN_EXPIRE_S", DEFAULT_PRESIGN_EXPIRE_S)
        )

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint_url and self.access_key and self.secret_key)


def build_incident_object_key(
    *,
    camera_id: str,
    camera_name: str,
    event_id: str,
    at: datetime | None = None,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    when = at if at is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(timezone.utc) + timedelta(hours=utc_offset_hours())
    date_str = local.strftime("%d-%m-%Y")
    hour_folder = f"{local.strftime('%H')}00"
    label = (camera_name or camera_id or "camera").strip() or "camera"
    safe_cam = re.sub(r"[^\w.-]+", "_", label)[:64]
    safe_ev = re.sub(r"[^\w.-]+", "_", event_id)[:80] or "event"
    root = (prefix or DEFAULT_PREFIX).strip("/")
    return "/".join((root, date_str, safe_cam, hour_folder, f"{safe_ev}.mp4"))


class MinioStore:
    def __init__(self, config: MinioConfig | None = None) -> None:
        self.config = config or MinioConfig()
        self._client: Any = None
        self._bucket_ready = False

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _client_or_none(self) -> Any | None:
        if not self.config.enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            logger.warning("boto3 is not installed — MinIO uploads disabled")
            return None
        self._client = boto3.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            region_name=self.config.region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        return self._client

    def ensure_bucket(self) -> bool:
        client = self._client_or_none()
        if client is None:
            return False
        if self._bucket_ready:
            return True
        bucket = self.config.bucket
        try:
            client.head_bucket(Bucket=bucket)
        except Exception:
            try:
                client.create_bucket(Bucket=bucket)
            except Exception:
                logger.exception("MinIO: failed to create bucket=%s", bucket)
                return False
        self._bucket_ready = True
        return True

    def upload_file(self, file_path: Path, key: str) -> bool:
        client = self._client_or_none()
        if client is None:
            return False
        if not self.ensure_bucket():
            return False
        try:
            client.upload_file(
                str(file_path),
                self.config.bucket,
                key,
                ExtraArgs={"ContentType": "video/mp4"},
            )
        except Exception:
            logger.exception(
                "MinIO upload failed bucket=%s key=%s", self.config.bucket, key
            )
            return False
        logger.info("MinIO uploaded bucket=%s key=%s", self.config.bucket, key)
        return True

    def object_url(self, key: str) -> str:
        client = self._client_or_none()
        if client is None:
            return ""
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": key},
                ExpiresIn=self.config.presign_expire_s,
            )
        except Exception:
            logger.exception("MinIO presign failed key=%s", key)
            return self._public_path_url(key)
        return self._rewrite_public(url) or url

    def _public_path_url(self, key: str) -> str:
        base = self.config.public_url or self.config.endpoint_url.rstrip("/")
        if not base:
            return ""
        return f"{base}/{self.config.bucket}/{key}"

    def _rewrite_public(self, url: str) -> str:
        public = self.config.public_url
        if not public:
            return url
        parsed = urlparse(url)
        pub = urlparse(public)
        if not pub.scheme or not pub.netloc:
            return url
        return urlunparse(
            (
                pub.scheme,
                pub.netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )


_store: MinioStore | None = None


def get_minio_store() -> MinioStore:
    global _store
    if _store is None:
        _store = MinioStore()
    return _store
