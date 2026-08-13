#!/bin/bash
# First start of the GPU video container: prepare YOLO11n if missing, then run the pipeline.
set -euo pipefail

export NEXUS_DS_ROLE=video
export NEXUS_DS_DATA_DIR="${NEXUS_DS_DATA_DIR:-/data/nexus_deepstream}"
export PYTHONPATH="/opt/nexus_deepstream${PYTHONPATH:+:$PYTHONPATH}"
export NEXUS_DS_VIDEO_HOST="${NEXUS_DS_VIDEO_HOST:-0.0.0.0}"
export NEXUS_DS_VIDEO_PORT="${NEXUS_DS_VIDEO_PORT:-8081}"
export DEEPSTREAM_YOLO_DIR="${DEEPSTREAM_YOLO_DIR:-/opt/nexus_deepstream/models/yolo11n}"
export DEEPSTREAM_WORK_DIR="${DEEPSTREAM_WORK_DIR:-/tmp/nexus_deepstream}"
export DEEPSTREAM_DEBUG_DIR="${DEEPSTREAM_DEBUG_DIR:-${NEXUS_DS_DATA_DIR}/debug}"
export CUDA_VER="${CUDA_VER:-13.1}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: python not found"
  exit 127
fi

mkdir -p "${NEXUS_DS_DATA_DIR}" "${DEEPSTREAM_WORK_DIR}" "${DEEPSTREAM_DEBUG_DIR}"

ONNX="${DEEPSTREAM_YOLO_DIR}/yolo11n.onnx"
CUSTOM_LIB="${DEEPSTREAM_YOLO_DIR}/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so"
PREPARE="${DEEPSTREAM_YOLO_DIR}/prepare.sh"

if [ ! -f "${ONNX}" ] || [ ! -f "${CUSTOM_LIB}" ]; then
  if [ ! -f "${PREPARE}" ]; then
    echo "ERROR: YOLO11n ONNX missing: ${ONNX}"
    echo "ERROR: ${PREPARE} not found. Mount ./models into the video container."
    exit 1
  fi
  echo "YOLO11n missing — first boot, running prepare.sh (needs internet, several minutes)"
  python3 -c 'from pathlib import Path; import sys; Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes().replace(b"\r", b""))' \
    "${PREPARE}" /tmp/yolo11n-prepare.sh
  chmod +x /tmp/yolo11n-prepare.sh
  /bin/bash /tmp/yolo11n-prepare.sh
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

echo "Starting Nexus DeepStream video"
cd /opt/nexus_deepstream
exec "${PY}" -m app.video
