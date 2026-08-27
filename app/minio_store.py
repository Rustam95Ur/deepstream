"""MinIO / S3-compatible storage for incident clips."""

from __future__ import annotations

import logging
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "incidents"
DEFAULT_PREFIX = "incidents/"
DEFAULT_REGION = "us-east-1"
DEFAULT_PRESIGN_EXPIRE_S = 7 * 24 * 3600
DEFAULT_PUBLIC_PORT = "8080"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
# Docker Desktop hostname — missing on Ubuntu unless extra_hosts is set.
DOCKER_HOST_NAMES = {"host.docker.internal", "gateway.docker.internal"}


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


def _replace_url_host(url: str, advertised_host: str) -> str:
    parsed = urlparse(url)
    if not advertised_host:
        return url
    port = parsed.port
    netloc = advertised_host if port is None else f"{advertised_host}:{port}"
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    return urlunparse(
        (
            parsed.scheme or "http",
            f"{userinfo}{netloc}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _resolve_ipv4(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return ""
    if not infos:
        return ""
    ip = str(infos[0][4][0] or "").strip()
    return ip if ip not in LOOPBACK_HOSTS else ""


def host_ipv4_for_campus() -> str:
    """
    IPv4 of this Docker host as seen from Campus on the same Ubuntu machine.

    Prefer ``host.docker.internal`` (compose ``extra_hosts: host-gateway``), then
    docker0 ``172.17.0.1``. Do not use the compose overlay gateway (172.18+) —
    Campus is on another network and cannot reach it.
    """
    for name in ("host.docker.internal", "gateway.docker.internal"):
        ip = _resolve_ipv4(name)
        if ip:
            return ip
    return "172.17.0.1"


def _host_unreachable_from_campus(host: str) -> bool:
    name = (host or "").strip().lower()
    return not name or name in LOOPBACK_HOSTS or name in DOCKER_HOST_NAMES


_advertised_base_warned = False


def advertised_public_base() -> str:
    """
    Base URL Campus can GET (nginx published on the Ubuntu host).

    Never advertise loopback or ``host.docker.internal``: Campus is another
    Linux container and those names point at Campus itself or do not resolve.
    """
    global _advertised_base_warned
    port = (
        _env("NEXUS_DS_ADVERTISE_PORT") or _env("NEXUS_DS_PORT") or DEFAULT_PUBLIC_PORT
    )
    raw = _env("NEXUS_DS_PUBLIC_URL").rstrip("/")
    parsed = urlparse(raw) if raw else urlparse("")
    host = (parsed.hostname or "").strip()
    if raw and not _host_unreachable_from_campus(host):
        return raw
    ip = host_ipv4_for_campus()
    if raw:
        advertised = _replace_url_host(raw, ip).rstrip("/")
    else:
        advertised = f"http://{ip}:{port}"
    if advertised != raw and not _advertised_base_warned:
        _advertised_base_warned = True
        if raw and _host_unreachable_from_campus(host):
            logger.warning(
                "NEXUS_DS_PUBLIC_URL=%r is not reachable from Campus; using %s",
                raw,
                advertised,
            )
        else:
            logger.info(
                "Campus clip base %s (no .env NEXUS_DS_PUBLIC_URL needed)", advertised
            )
    return advertised


def campus_clip_url(event_id: str) -> str:
    eid = (event_id or "").strip().removesuffix(".mp4")
    if not eid:
        return ""
    return f"{advertised_public_base()}/api/v1/public/clips/{eid}.mp4"


def build_incident_object_key(
    *,
    camera_id: str,
    camera_name: str,
    event_id: str,
    at: datetime | None = None,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    """MinIO key: ``{prefix}{DD-MM-YYYY}/{camera}/{HH}00/{HH:MM}-{event_id}.mp4``."""
    when = at if at is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(timezone.utc) + timedelta(hours=utc_offset_hours())
    date_str = local.strftime("%d-%m-%Y")
    hour_folder = f"{local.strftime('%H')}00"
    time_str = local.strftime("%H:%M")
    label = (camera_name or camera_id or "camera").strip() or "camera"
    safe_cam = re.sub(r"[^\w.-]+", "_", label)[:64]
    safe_ev = re.sub(r"[^\w.-]+", "_", event_id)[:80] or "event"
    root = (prefix or DEFAULT_PREFIX).strip("/")
    filename = f"{time_str}-{safe_ev}.mp4"
    return "/".join((root, date_str, safe_cam, hour_folder, filename))


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

    def iter_object(
        self, key: str, chunk_size: int = 64 * 1024
    ) -> tuple[Iterator[bytes], int] | None:
        client = self._client_or_none()
        if client is None:
            return None
        try:
            resp = client.get_object(Bucket=self.config.bucket, Key=key)
        except Exception:
            logger.exception(
                "MinIO get_object failed bucket=%s key=%s", self.config.bucket, key
            )
            return None
        body = resp["Body"]
        length = int(resp.get("ContentLength") or 0)

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    data = body.read(chunk_size)
                    if not data:
                        break
                    yield data
            finally:
                body.close()

        return chunks(), length

    def get_object_bytes(
        self, key: str, *, max_bytes: int = 200 * 1024 * 1024
    ) -> bytes | None:
        """Load a whole object into memory (capped). Used for webhook multipart."""
        streamed = self.iter_object(key)
        if streamed is None:
            return None
        chunks, length = streamed
        if length and length > max_bytes:
            logger.warning(
                "MinIO object too large for webhook key=%s size=%s max=%s",
                key,
                length,
                max_bytes,
            )
            # Drain and discard.
            for _ in chunks:
                pass
            return None
        parts: list[bytes] = []
        total = 0
        for chunk in chunks:
            total += len(chunk)
            if total > max_bytes:
                logger.warning(
                    "MinIO object exceeded webhook size cap key=%s",
                    key,
                )
                return None
            parts.append(chunk)
        return b"".join(parts)

    def get_object_bytes(self, key: str) -> bytes | None:
        streamed = self.iter_object(key)
        if streamed is None:
            return None
        chunks, _length = streamed
        try:
            return b"".join(chunks)
        except Exception:
            logger.exception("MinIO read failed key=%s", key)
            return None

    def _presign_client(self) -> Any | None:
        """Sign against the advertised host so SigV4 ``Host`` matches the URL."""
        public = self.config.public_url
        if not public:
            return self._client_or_none()
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            return self._client_or_none()
        return boto3.client(
            "s3",
            endpoint_url=public,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            region_name=self.config.region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    def object_url(self, key: str) -> str:
        client = self._presign_client()
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
        if self.config.public_url:
            return url
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
