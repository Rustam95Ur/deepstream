#!/bin/bash
# Download RTMPose (OpenMMLab, Apache-2.0) ONNX and add the keypoint decode to the graph.
# Output: ${DEEPSTREAM_MODEL_DIR}/rtmpose/rtmpose_kpts.onnx  (input N x 3 x 256 x 192,
#         output 'keypoints' N x 17 x 3 = x, y in network pixels, score).
# Licence note: the default checkpoint is trained on "body7" (COCO + 6 other public pose
# datasets, some with research-only terms). Point RTMPOSE_ZIP_URL / RTMPOSE_ONNX at a
# COCO-only export if legal requires it -- no code change needed, same input/outputs.
set -euo pipefail

MODEL_DIR="${DEEPSTREAM_MODEL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROOT="${MODEL_DIR}/rtmpose"
OUT="${ROOT}/rtmpose_kpts.onnx"
CACHE="${DEEPSTREAM_MODEL_CACHE:-/tmp/nexus_deepstream_model_cache}"
ZIP_URL="${RTMPOSE_ZIP_URL:-https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip}"

log() { echo "[rtmpose-prepare] $*"; }

if [ -s "${OUT}" ]; then
  log "Already prepared: ${OUT}"
  exit 0
fi
mkdir -p "${ROOT}" "${CACHE}"

download() {
  local url="$1" dest="$2"
  if command -v wget >/dev/null 2>&1; then
    wget -q --tries=3 -O "${dest}" "${url}"
  else
    curl -fsSL --retry 3 -o "${dest}" "${url}"
  fi
}

SRC="${RTMPOSE_ONNX:-}"
if [ -z "${SRC}" ]; then
  ZIP="${CACHE}/$(basename "${ZIP_URL}")"
  if [ ! -s "${ZIP}" ]; then
    log "downloading $(basename "${ZIP_URL}")"
    download "${ZIP_URL}" "${ZIP}.part"
    mv "${ZIP}.part" "${ZIP}"
  fi
  SRC="$(python3 - "${ZIP}" "${CACHE}/rtmpose_unzip" <<'PY'
import sys, zipfile, pathlib
z, out = sys.argv[1], pathlib.Path(sys.argv[2])
zipfile.ZipFile(z).extractall(out)
cands = sorted(out.rglob("*.onnx"))
if not cands:
    sys.exit("no .onnx inside " + z)
print(cands[0])
PY
)"
fi
log "source ONNX: ${SRC}"

VENV="${CACHE}/venv"
if [ ! -x "${VENV}/bin/python" ]; then
  log "creating venv for the ONNX edit"
  if ! python3 -m venv "${VENV}" 2>/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends python3-venv python3-pip
    python3 -m venv "${VENV}"
  fi
fi
"${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check onnx

SCRIPT_DIR="${MODEL_DIR}/rtmpose"
"${VENV}/bin/python" "${SCRIPT_DIR}/add_decode.py" "${SRC}" "${OUT}.part"
mv "${OUT}.part" "${OUT}"
log "Ready: ${OUT}"
