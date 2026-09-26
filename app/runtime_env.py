"""Boot-time environment knobs (read once; restart to pick up changes).

Compose note: service name ``pipeline`` runs role ``video``
(``NEXUS_DS_ROLE=video``, container ``nexus-deepstream-video``).
API reaches it via ``NEXUS_DS_VIDEO_URL=http://pipeline:8081``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.env import env_float, env_int, env_str


def _default_data_dir() -> Path:
    raw = env_str("NEXUS_DS_DATA_DIR")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True, slots=True)
class RuntimeEnv:
    # API listen (control plane)
    host: str
    port: int
    data_dir: Path
    yolo_dir: Path
    work_dir: Path
    debug_dir: Path

    # Video control plane (:8081)
    video_host: str
    video_port: int
    video_url: str
    video_token: str

    # Postgres pool (app traffic via PgBouncer)
    db_pool_size: int
    db_max_overflow: int
    db_pool_recycle: int
    db_pool_timeout: int
    db_statement_timeout_ms: int

    # Camera list cache
    camera_cache_ms: int

    # Async sink / history writers
    sink_queue: int
    sink_workers: int
    sink_close_s: float
    history_queue: int
    history_batch: int
    history_flush_ms: int

    # Ring-buffer
    ring_segment_dur_sec: int
    ring_keep_s: int
    ring_edge_margin_s: float
    ring_latency_ms: int
    ring_stagger_sec: float
    ring_stall_multiplier: float
    ring_max_restart_backoff_sec: int
    ring_camera_refresh_sec: int
    ring_gc_interval_sec: int
    ring_muxer: str
    ring_default_codec: str
    ring_segment_dir: str
    clips_dir: str

    # MinIO / public clip URLs
    minio_endpoint_url: str
    minio_access_key: str
    minio_secret_key: str
    minio_region: str
    minio_bucket: str
    minio_key_prefix: str
    minio_public_url: str
    minio_presign_expire_s: int
    public_url: str
    advertise_port: str
    utc_offset_hours: int


_env: RuntimeEnv | None = None


def load_runtime_env() -> RuntimeEnv:
    data_dir = _default_data_dir()
    root = Path(__file__).resolve().parent.parent
    return RuntimeEnv(
        host=env_str("NEXUS_DS_HOST", "0.0.0.0") or "0.0.0.0",
        port=env_int("NEXUS_DS_PORT", 8080),
        data_dir=data_dir,
        yolo_dir=Path(
            env_str("DEEPSTREAM_YOLO_DIR") or str(root / "models" / "yolo11n")
        ),
        work_dir=Path(env_str("DEEPSTREAM_WORK_DIR") or "/tmp/nexus_deepstream"),
        debug_dir=Path(env_str("DEEPSTREAM_DEBUG_DIR") or str(data_dir / "debug")),
        video_host=env_str("NEXUS_DS_VIDEO_HOST", "0.0.0.0") or "0.0.0.0",
        video_port=env_int("NEXUS_DS_VIDEO_PORT", 8081),
        video_url=env_str("NEXUS_DS_VIDEO_URL").rstrip("/"),
        video_token=env_str("NEXUS_DS_VIDEO_TOKEN"),
        db_pool_size=env_int("NEXUS_DS_DB_POOL_SIZE", 20),
        db_max_overflow=env_int("NEXUS_DS_DB_MAX_OVERFLOW", 40),
        db_pool_recycle=env_int("NEXUS_DS_DB_POOL_RECYCLE", 180),
        db_pool_timeout=env_int("NEXUS_DS_DB_POOL_TIMEOUT", 10),
        db_statement_timeout_ms=env_int("NEXUS_DS_DB_STATEMENT_TIMEOUT_MS", 5000),
        camera_cache_ms=env_int("NEXUS_DS_CAMERA_CACHE_MS", 2000),
        sink_queue=env_int("NEXUS_DS_SINK_QUEUE", 10000),
        sink_workers=env_int("NEXUS_DS_SINK_WORKERS", 4),
        sink_close_s=env_float("NEXUS_DS_SINK_CLOSE_S", 120.0),
        history_queue=env_int("NEXUS_DS_HISTORY_QUEUE", 20000),
        history_batch=env_int("NEXUS_DS_HISTORY_BATCH", 200),
        history_flush_ms=env_int("NEXUS_DS_HISTORY_FLUSH_MS", 200),
        ring_segment_dur_sec=env_int("NEXUS_DS_RING_SEGMENT_DUR_SEC", 3),
        ring_keep_s=env_int("NEXUS_DS_RING_KEEP_S", 90),
        ring_edge_margin_s=env_float("NEXUS_DS_RING_EDGE_MARGIN_S", 2.0),
        ring_latency_ms=env_int("NEXUS_DS_RING_LATENCY_MS", 200),
        ring_stagger_sec=env_float("NEXUS_DS_RING_STAGGER_SEC", 0.3),
        ring_stall_multiplier=env_float("NEXUS_DS_RING_STALL_MULTIPLIER", 3.0),
        ring_max_restart_backoff_sec=env_int("NEXUS_DS_RING_MAX_RESTART_BACKOFF_SEC", 60),
        ring_camera_refresh_sec=env_int("NEXUS_DS_RING_CAMERA_REFRESH_SEC", 60),
        ring_gc_interval_sec=env_int("NEXUS_DS_RING_GC_INTERVAL_SEC", 30),
        ring_muxer=(env_str("NEXUS_DS_RING_MUXER", "mp4mux") or "mp4mux").lower(),
        ring_default_codec=(
            env_str("NEXUS_DS_RING_DEFAULT_CODEC", "h265") or "h265"
        ).lower(),
        ring_segment_dir=env_str("NEXUS_DS_RING_SEGMENT_DIR"),
        clips_dir=env_str("NEXUS_DS_CLIPS_DIR"),
        minio_endpoint_url=env_str("NEXUS_DS_MINIO_ENDPOINT_URL"),
        minio_access_key=env_str("NEXUS_DS_MINIO_ACCESS_KEY"),
        minio_secret_key=env_str("NEXUS_DS_MINIO_SECRET_KEY"),
        minio_region=env_str("NEXUS_DS_MINIO_REGION", "us-east-1") or "us-east-1",
        minio_bucket=env_str("NEXUS_DS_MINIO_BUCKET", "incidents") or "incidents",
        minio_key_prefix=env_str("NEXUS_DS_MINIO_KEY_PREFIX", "incidents/")
        or "incidents/",
        minio_public_url=env_str("NEXUS_DS_MINIO_PUBLIC_URL").rstrip("/"),
        minio_presign_expire_s=env_int(
            "NEXUS_DS_MINIO_PRESIGN_EXPIRE_S", 7 * 24 * 3600
        ),
        public_url=env_str("NEXUS_DS_PUBLIC_URL").rstrip("/"),
        advertise_port=env_str("NEXUS_DS_ADVERTISE_PORT"),
        utc_offset_hours=env_int("NEXUS_DS_UTC_OFFSET_HOURS", 5),
    )


def get_runtime_env() -> RuntimeEnv:
    global _env
    if _env is None:
        _env = load_runtime_env()
    return _env


def reset_runtime_env() -> None:
    """Drop cached env (tests / after mutating os.environ in-process)."""
    global _env
    _env = None
