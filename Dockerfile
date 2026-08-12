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
    PYTHONPATH=/opt/nexus_deepstream

WORKDIR /opt/nexus_deepstream

COPY pyproject.toml poetry.lock /opt/nexus_deepstream/
RUN (python3 -m pip install --quiet --disable-pip-version-check --break-system-packages \
      "poetry==${POETRY_VERSION}" \
    || python3 -m pip install --quiet --disable-pip-version-check \
      "poetry==${POETRY_VERSION}") \
    && poetry install --only main --no-root --no-ansi

COPY app /opt/nexus_deepstream/app
COPY shell/boot.sh /opt/nexus_deepstream/shell/boot.sh
# Optional: bake models (or mount at runtime)
COPY models /opt/nexus_deepstream/models

RUN mkdir -p /data/nexus_deepstream /tmp/nexus_deepstream \
    && chmod +x /opt/nexus_deepstream/shell/boot.sh \
    && tr -d '\r' < /opt/nexus_deepstream/shell/boot.sh > /tmp/boot.sh \
    && mv /tmp/boot.sh /opt/nexus_deepstream/shell/boot.sh \
    && chmod +x /opt/nexus_deepstream/shell/boot.sh

EXPOSE 8080
VOLUME ["/data/nexus_deepstream"]

CMD ["/bin/bash", "/opt/nexus_deepstream/shell/boot.sh"]
