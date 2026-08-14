#!/bin/sh
# Publishes RTSP to MediaMTX.
# If /video/cam1.mp4 exists, loops that file; otherwise uses lavfi testsrc.

set -eu

RTSP_URL="${RTSP_URL:-rtsp://mediamtx:8554/cam1}"
VIDEO_FILE="${VIDEO_FILE:-/video/cam1.mp4}"
VIDEO_SIZE="${VIDEO_SIZE:-1280x720}"
FPS="${FPS:-25}"

echo "Waiting for MediaMTX..."
sleep 3

if [ -f "${VIDEO_FILE}" ]; then
  echo "Publishing file -> ${RTSP_URL} (${VIDEO_FILE})"
  exec ffmpeg -hide_banner -loglevel info -re -stream_loop -1 \
    -i "${VIDEO_FILE}" \
    -map 0:v:0 \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -g "${FPS}" -keyint_min "${FPS}" \
    -an \
    -f rtsp -rtsp_transport tcp \
    "${RTSP_URL}"
fi

echo "No ${VIDEO_FILE}; publishing testsrc -> ${RTSP_URL} (${VIDEO_SIZE}@${FPS})"
exec ffmpeg -hide_banner -loglevel info -re \
  -f lavfi -i "testsrc=size=${VIDEO_SIZE}:rate=${FPS},format=yuv420p" \
  -f lavfi -i "sine=frequency=1000:sample_rate=44100" \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -g "${FPS}" -keyint_min "${FPS}" \
  -c:a aac -b:a 128k \
  -f rtsp -rtsp_transport tcp \
  "${RTSP_URL}"
