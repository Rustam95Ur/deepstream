#!/bin/bash
# First start of the GPU video container: download PeopleNet + RTMPose if missing, then run the pipeline.
set -euo pipefail

export NEXUS_DS_ROLE=video
export NEXUS_DS_DATA_DIR="${NEXUS_DS_DATA_DIR:-/data/nexus_deepstream}"
export PYTHONPATH="/opt/nexus_deepstream${PYTHONPATH:+:$PYTHONPATH}"
export NEXUS_DS_VIDEO_HOST="${NEXUS_DS_VIDEO_HOST:-0.0.0.0}"
export NEXUS_DS_VIDEO_PORT="${NEXUS_DS_VIDEO_PORT:-8081}"
export DEEPSTREAM_MODEL_DIR="${DEEPSTREAM_MODEL_DIR:-/opt/nexus_deepstream/models}"
export DEEPSTREAM_WORK_DIR="${DEEPSTREAM_WORK_DIR:-/tmp/nexus_deepstream}"
export DEEPSTREAM_DEBUG_DIR="${DEEPSTREAM_DEBUG_DIR:-${NEXUS_DS_DATA_DIR}/debug}"
export CUDA_VER="${CUDA_VER:-13.1}"

# GStreamer/GLib opens a pipe per source; 128 RTSP hits default 1024 nofile.
ulimit -n 1048576 2>/dev/null || ulimit -n 65536 2>/dev/null || true
echo "nofile=$(ulimit -n)"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "ERROR: python not found"
  exit 127
fi

mkdir -p "${NEXUS_DS_DATA_DIR}" "${DEEPSTREAM_WORK_DIR}" "${DEEPSTREAM_DEBUG_DIR}"

# Runs models/<name>/prepare.sh when <file> is missing (CRLF-stripped copy in /tmp).
prepare_model() {
  local name="$1" need="$2" script="${DEEPSTREAM_MODEL_DIR}/$1/prepare.sh"
  if [ -s "${need}" ]; then
    return 0
  fi
  if [ ! -f "${script}" ]; then
    echo "ERROR: ${need} missing and ${script} not found. Mount ./models into the video container."
    return 1
  fi
  echo "${name} missing -- first boot, running prepare.sh (needs internet, a few minutes)"
  python3 -c 'from pathlib import Path; import sys; Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes().replace(b"\r", b""))' \
    "${script}" "/tmp/${name}-prepare.sh"
  /bin/bash "/tmp/${name}-prepare.sh"
}

prepare_model peoplenet "${DEEPSTREAM_MODEL_DIR}/peoplenet/resnet34_peoplenet.onnx"
if ! prepare_model rtmpose "${DEEPSTREAM_MODEL_DIR}/rtmpose/rtmpose_kpts.onnx"; then
  echo "WARNING: pose model unavailable -- the vif trigger runs on box contact only"
fi

echo "Starting Nexus DeepStream video"
cd /opt/nexus_deepstream
exec "${PY}" -m app.video
