#!/bin/bash
# Download NVIDIA TAO PeopleNet (ONNX) for DeepStream.
# No build step: nvinfer parses PeopleNet (DetectNet_v2) with its built-in parser.
# Classes: 0 person, 1 bag, 2 face. Licence: NVIDIA TAO model licence (see NGC model card).
set -euo pipefail

# boot.sh copies this script to /tmp to strip CRLF, so never derive the model dir from it there.
MODEL_DIR="${DEEPSTREAM_MODEL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROOT="${MODEL_DIR}/peoplenet"
VER="${PEOPLENET_VERSION:-deployable_quantized_onnx_v2.6.3}"
BASE="${PEOPLENET_BASE_URL:-https://api.ngc.nvidia.com/v2/models/org/nvidia/team/tao/peoplenet/${VER}/files?redirect=true&path=}"
FILES=(resnet34_peoplenet.onnx resnet34_peoplenet_int8.txt labels.txt)

log() { echo "[peoplenet-prepare] $*"; }

download() {
  local url="$1" dest="$2"
  if command -v wget >/dev/null 2>&1; then
    wget -q --tries=3 -O "${dest}" "${url}"
  else
    curl -fsSL --retry 3 -o "${dest}" "${url}"
  fi
}

mkdir -p "${ROOT}"
for f in "${FILES[@]}"; do
  if [ -s "${ROOT}/${f}" ]; then
    continue
  fi
  log "downloading ${f} (${VER})"
  download "${BASE}${f}" "${ROOT}/${f}.part"
  mv "${ROOT}/${f}.part" "${ROOT}/${f}"
done

if ! head -n1 "${ROOT}/labels.txt" | grep -qi person; then
  log "ERROR: ${ROOT}/labels.txt does not start with 'person': $(head -n3 "${ROOT}/labels.txt" | tr '\n' ' ')"
  exit 1
fi
log "Ready: ${ROOT}"
