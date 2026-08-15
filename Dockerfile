# Nexus DeepStream node — NVIDIA DeepStream 9 + FastAPI control plane
FROM nvcr.io/nvidia/deepstream:9.0-triton-multiarch

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    NEXUS_DS_HOST=0.0.0.0 \
    NEXUS_DS_PORT=8080 \
    NEXUS_DS_DATA_DIR=/data/nexus_deepstream \
    DEEPSTREAM_YOLO_DIR=/opt/nexus_deepstream/models/yolo11n \
    DEEPSTREAM_WORK_DIR=/tmp/nexus_deepstream \
    DEEPSTREAM_DEBUG_DIR=/data/nexus_deepstream/debug \
    CUDA_VER=13.1 \
    PYTHONPATH=/opt/nexus_deepstream \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /opt/nexus_deepstream

# NGC DeepStream ships a broken ffmpeg (missing libvpx.so.9). Apt does not replace it.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/ffprobe

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git wget ca-certificates build-essential python3-gi python3-gst-1.0 \
      gstreamer1.0-tools \
    && chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe \
    && /usr/local/bin/ffmpeg -hide_banner -version \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock /opt/nexus_deepstream/
RUN (python3 -m pip install --quiet --disable-pip-version-check --break-system-packages \
      "poetry==${POETRY_VERSION}" \
    || python3 -m pip install --quiet --disable-pip-version-check \
      "poetry==${POETRY_VERSION}") \
    && poetry install --only main --no-root --no-ansi

COPY app /opt/nexus_deepstream/app
COPY alembic.ini /opt/nexus_deepstream/alembic.ini
COPY alembic /opt/nexus_deepstream/alembic
COPY shell /opt/nexus_deepstream/shell
# Optional: bake models (or mount at runtime)
COPY models /opt/nexus_deepstream/models

RUN mkdir -p /data/nexus_deepstream /tmp/nexus_deepstream \
    && find /opt/nexus_deepstream/shell -type f -name '*.sh' -exec sh -c 'tr -d "\r" < "$1" > "$1.tmp" && mv "$1.tmp" "$1" && chmod +x "$1"' _ {} \; \
    && test -f /opt/nexus_deepstream/shell/boot.sh

EXPOSE 8080
VOLUME ["/data/nexus_deepstream"]

# NGC Triton/DeepStream ENTRYPOINT prints the license then exec's bash with no TTY (exit 0, restart loop).
ENTRYPOINT ["/bin/bash"]
CMD ["/opt/nexus_deepstream/shell/boot.sh"]
