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
  export DEEPSTREAM_MODEL_DIR="${DEEPSTREAM_MODEL_DIR:-/opt/nexus_deepstream/models}"
  export DEEPSTREAM_WORK_DIR="${DEEPSTREAM_WORK_DIR:-/tmp/nexus_deepstream}"
  export DEEPSTREAM_DEBUG_DIR="${DEEPSTREAM_DEBUG_DIR:-${NEXUS_DS_DATA_DIR}/debug}"
  export CUDA_VER="${CUDA_VER:-13.1}"
  mkdir -p "${NEXUS_DS_DATA_DIR}" "${DEEPSTREAM_WORK_DIR}" "${DEEPSTREAM_DEBUG_DIR}"

  for spec in "peoplenet:peoplenet/resnet34_peoplenet.onnx" "rtmpose:rtmpose/rtmpose_kpts.onnx"; do
    name="${spec%%:*}"; need="${DEEPSTREAM_MODEL_DIR}/${spec#*:}"
    PREPARE="${DEEPSTREAM_MODEL_DIR}/${name}/prepare.sh"
    if [ ! -s "${need}" ]; then
      if [ -f "${PREPARE}" ]; then
        echo "${name} missing; running prepare.sh (first run can take a few minutes)"
        python3 -c 'from pathlib import Path; import sys; Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes().replace(b"\r", b""))' \
          "${PREPARE}" "/tmp/${name}-prepare.sh"
        if ! /bin/bash "/tmp/${name}-prepare.sh"; then
          echo "ERROR: ${name} prepare failed (${need} missing)."
        fi
      else
        echo "ERROR: ${need} missing. Run models/${name}/prepare.sh"
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
