#!/bin/bash
# Boot Nexus DeepStream (API + optional GPU pipeline).
set -euo pipefail

echo "Starting Nexus DeepStream"

export NEXUS_DS_HOST="${NEXUS_DS_HOST:-0.0.0.0}"
export NEXUS_DS_PORT="${NEXUS_DS_PORT:-8080}"
export NEXUS_DS_DATA_DIR="${NEXUS_DS_DATA_DIR:-/data/nexus_deepstream}"
export DEEPSTREAM_YOLO_DIR="${DEEPSTREAM_YOLO_DIR:-/opt/nexus_deepstream/models/yolo11n}"
export DEEPSTREAM_WORK_DIR="${DEEPSTREAM_WORK_DIR:-/tmp/nexus_deepstream}"
export DEEPSTREAM_DEBUG_DIR="${DEEPSTREAM_DEBUG_DIR:-${NEXUS_DS_DATA_DIR}/debug}"
export PYTHONPATH="/opt/nexus_deepstream${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_VER="${CUDA_VER:-13.1}"

mkdir -p "${NEXUS_DS_DATA_DIR}" "${DEEPSTREAM_WORK_DIR}" "${DEEPSTREAM_DEBUG_DIR}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: python not found"
  exit 127
fi

PREPARE="${DEEPSTREAM_YOLO_DIR}/prepare.sh"
if [ -f "${PREPARE}" ]; then
  tr -d '\r' < "${PREPARE}" > /tmp/yolo11n-prepare.sh
  chmod +x /tmp/yolo11n-prepare.sh
  /bin/bash /tmp/yolo11n-prepare.sh || true
fi

for eng in /opt/nvidia/deepstream/deepstream-9.0/model_b*_gpu0_fp16.engine; do
  if [ -f "${eng}" ]; then
    base="$(basename "${eng}")"
    if [ ! -f "${DEEPSTREAM_YOLO_DIR}/${base}" ]; then
      echo "Copying TensorRT engine ${base} -> ${DEEPSTREAM_YOLO_DIR}/"
      cp -n "${eng}" "${DEEPSTREAM_YOLO_DIR}/${base}" || true
    fi
  fi
done

cd /opt/nexus_deepstream
exec "${PY}" -m uvicorn app.main:app --host "${NEXUS_DS_HOST}" --port "${NEXUS_DS_PORT}"
