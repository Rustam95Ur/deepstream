#!/bin/bash
# Prepare YOLO11n for DeepStream: ONNX + custom parser.
# Intended to run inside the nexus-deepstream container (Linux + CUDA + DeepStream).
# First run needs internet and can take several minutes.
set -euo pipefail

# boot.sh copies this script to /tmp to strip CRLF; never use that as the model dir.
if [ -n "${DEEPSTREAM_YOLO_DIR:-}" ]; then
  ROOT="${DEEPSTREAM_YOLO_DIR}"
else
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
CACHE="${DEEPSTREAM_YOLO_CACHE:-/tmp/nexus_deepstream_yolo_cache}"
DSYOLO="${CACHE}/DeepStream-Yolo"
ONNX="${ROOT}/yolo11n.onnx"
LABELS="${ROOT}/labels.txt"
LIBDIR="${ROOT}/nvdsinfer_custom_impl_Yolo"
LIB="${LIBDIR}/libnvdsinfer_custom_impl_Yolo.so"
PT="${CACHE}/yolo11n.pt"
PT_URL="${YOLO11N_PT_URL:-https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt}"
DSYOLO_REPO="${DEEPSTREAM_YOLO_REPO:-https://github.com/marcoslucianops/DeepStream-Yolo.git}"

log() { echo "[yolo11n-prepare] $*"; }

if [ "$(uname -s)" != "Linux" ]; then
  log "This script must run in the Linux DeepStream container:"
  log "  docker compose exec nexus-deepstream-video bash /opt/nexus_deepstream/models/yolo11n/prepare.sh"
  exit 1
fi

if [ -f "${ONNX}" ] && [ -f "${LIB}" ] && [ -f "${LABELS}" ]; then
  log "Already prepared:"
  log "  ${ONNX}"
  log "  ${LIB}"
  log "  ${LABELS}"
  exit 0
fi

mkdir -p "${CACHE}" "${LIBDIR}"

need_pkgs=()
command -v git >/dev/null 2>&1 || need_pkgs+=(git)
command -v make >/dev/null 2>&1 || need_pkgs+=(make)
command -v g++ >/dev/null 2>&1 || need_pkgs+=(g++ build-essential)
command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1 || need_pkgs+=(wget)
if [ ${#need_pkgs[@]} -gt 0 ]; then
  log "Installing packages: ${need_pkgs[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends "${need_pkgs[@]}"
fi

download() {
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 -o "${dest}" "${url}"
  else
    wget -q -O "${dest}" "${url}"
  fi
}

detect_cuda_ver() {
  if [ -n "${CUDA_VER:-}" ] && [ -x "/usr/local/cuda-${CUDA_VER}/bin/nvcc" ]; then
    echo "${CUDA_VER}"
    return
  fi
  local nvcc=""
  if [ -x /usr/local/cuda/bin/nvcc ]; then
    nvcc=/usr/local/cuda/bin/nvcc
  elif command -v nvcc >/dev/null 2>&1; then
    nvcc="$(command -v nvcc)"
  fi
  if [ -n "${nvcc}" ]; then
    "${nvcc}" --version | sed -n 's/.*release \([0-9]\+\.[0-9]\+\).*/\1/p' | head -n1
    return
  fi
  echo "${CUDA_VER:-13.1}"
}

export CUDA_VER
CUDA_VER="$(detect_cuda_ver)"
log "CUDA_VER=${CUDA_VER}"

if [ ! -d "${DSYOLO}/.git" ]; then
  log "Cloning DeepStream-Yolo"
  rm -rf "${DSYOLO}"
  git clone --depth 1 "${DSYOLO_REPO}" "${DSYOLO}"
fi

if [ ! -f "${LIB}" ]; then
  if [ ! -x "/usr/local/cuda-${CUDA_VER}/bin/nvcc" ]; then
    log "ERROR: nvcc not found at /usr/local/cuda-${CUDA_VER}/bin/nvcc"
    log "Set CUDA_VER to match the CUDA toolkit in this image."
    exit 1
  fi
  log "Building nvdsinfer_custom_impl_Yolo (CUDA_VER=${CUDA_VER})"
  make -C "${DSYOLO}/nvdsinfer_custom_impl_Yolo"
  cp -f "${DSYOLO}/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so" "${LIB}"
  log "Wrote ${LIB}"
fi

if [ ! -f "${ONNX}" ]; then
  VENV="${CACHE}/venv"
  if [ ! -x "${VENV}/bin/python" ]; then
    log "Creating export venv"
    if ! python3 -m venv "${VENV}" 2>/dev/null; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y --no-install-recommends python3-venv python3-pip
      python3 -m venv "${VENV}"
    fi
  fi
  log "Installing Ultralytics + ONNX exporters"
  "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check -U pip
  "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check \
    ultralytics onnx onnxslim onnxruntime onnxscript

  if [ ! -f "${PT}" ]; then
    log "Downloading ${PT_URL}"
    download "${PT_URL}" "${PT}"
  fi

  log "Exporting yolo11n.onnx (DeepStream-Yolo format, dynamic batch)"
  export YOLO_CONFIG_DIR="${CACHE}/ultralytics"
  mkdir -p "${YOLO_CONFIG_DIR}"
  cp -f "${DSYOLO}/utils/export_yolo11.py" "${CACHE}/export_yolo11.py"
  (
    cd "${CACHE}"
    "${VENV}/bin/python" export_yolo11.py -w yolo11n.pt --dynamic --simplify
  )
  cp -f "${CACHE}/yolo11n.onnx" "${ONNX}"
  if [ ! -f "${LABELS}" ] && [ -f "${CACHE}/labels.txt" ]; then
    cp -f "${CACHE}/labels.txt" "${LABELS}"
  fi
  log "Wrote ${ONNX}"
fi

if [ ! -f "${LABELS}" ]; then
  log "ERROR: labels.txt missing at ${LABELS}"
  exit 1
fi

log "Ready."
log "  ${ONNX}"
log "  ${LIB}"
log "  ${LABELS}"
