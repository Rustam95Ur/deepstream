#!/bin/sh
# Start the local MediaMTX + ffmpeg testsrc publisher.

set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker compose -f docker-compose.rtsp-test.yml up -d

echo "RTSP:   rtsp://127.0.0.1:8554/cam1"
echo "HLS:    http://127.0.0.1:8888/cam1/"
echo "WebRTC: http://127.0.0.1:8889/cam1/"
echo "In the video container use: rtsp://mediamtx:8554/cam1"
