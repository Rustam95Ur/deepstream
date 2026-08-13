#!/bin/bash
# Boot Nexus DeepStream: API (default) or video (NEXUS_DS_ROLE=video).
set -euo pipefail

ROLE="${NEXUS_DS_ROLE:-api}"
export NEXUS_DS_DATA_DIR="${NEXUS_DS_DATA_DIR:-/data/nexus_deepstream}"
export PYTHONPATH="/opt/nexus_deepstream${PYTHONPATH:+:$PYTHONPATH}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: python not found"
  exit 127
fi

if [ "${ROLE}" = "video" ]; then
  echo "Starting Nexus DeepStream video"
  export NEXUS_DS_VIDEO_HOST="${NEXUS_DS_VIDEO_HOST:-0.0.0.0}"
  export NEXUS_DS_VIDEO_PORT="${NEXUS_DS_VIDEO_PORT:-8081}"
  export DEEPSTREAM_YOLO_DIR="${DEEPSTREAM_YOLO_DIR:-/opt/nexus_deepstream/models/yolo11n}"
  export DEEPSTREAM_WORK_DIR="${DEEPSTREAM_WORK_DIR:-/tmp/nexus_deepstream}"
  export DEEPSTREAM_DEBUG_DIR="${DEEPSTREAM_DEBUG_DIR:-${NEXUS_DS_DATA_DIR}/debug}"
  export CUDA_VER="${CUDA_VER:-13.1}"
  mkdir -p "${NEXUS_DS_DATA_DIR}" "${DEEPSTREAM_WORK_DIR}" "${DEEPSTREAM_DEBUG_DIR}"

  ONNX="${DEEPSTREAM_YOLO_DIR}/yolo11n.onnx"
  CUSTOM_LIB="${DEEPSTREAM_YOLO_DIR}/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so"
  PREPARE="${DEEPSTREAM_YOLO_DIR}/prepare.sh"
  if [ ! -f "${ONNX}" ] || [ ! -f "${CUSTOM_LIB}" ]; then
    if [ -f "${PREPARE}" ]; then
      echo "YOLO11n artifacts missing; running prepare.sh (first run can take several minutes)"
      tr -d '\r' < "${PREPARE}" > /tmp/yolo11n-prepare.sh
      chmod +x /tmp/yolo11n-prepare.sh
      if ! /bin/bash /tmp/yolo11n-prepare.sh; then
        echo "ERROR: YOLO prepare failed. Pipeline will idle until ${ONNX} and the custom parser exist."
      fi
    else
      echo "ERROR: YOLO11n ONNX missing: ${ONNX}. Run models/yolo11n/prepare.sh"
    fi
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
  exec "${PY}" -m app.video
fi

echo "Starting Nexus DeepStream API"
export NEXUS_DS_HOST="${NEXUS_DS_HOST:-0.0.0.0}"
export NEXUS_DS_PORT="${NEXUS_DS_PORT:-8080}"
mkdir -p "${NEXUS_DS_DATA_DIR}"
cd /opt/nexus_deepstream
exec "${PY}" -m uvicorn app.main:app \
  --host "${NEXUS_DS_HOST}" \
  --port "${NEXUS_DS_PORT}" \
  --workers 1 \
  --timeout-keep-alive 30 \
  --backlog 2048 \
  --limit-concurrency 200 \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  --no-access-log
