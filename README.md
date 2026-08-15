# Nexus DeepStream

Standalone DeepStream first-line node: FastAPI control plane + GPU pipeline.
One Django Campus can attach multiple nodes (different GPUs / machines).

## Features

- Local camera registry (`GET/POST/PUT/PATCH/DELETE /api/v1/cameras`) — Django pushes and pulls like SmartBox channels
- Settings UI at `/` (Vue SPA behind nginx in Docker)
- Multiple webhooks: retries, dead-letter queue, resend from history
- Incident clip from the RTSP ring-buffer (Campus `rtsp_writer` path) uploaded to MinIO; payload always has `event_id`, `clip`, `video_url`
- Per-camera enable/disable of `presence`, `convergence`, `vif`, `stream_silent` (or inherit node settings)
- Pipeline runs in a separate GPU process when `pyservicemaker` is available

## Quick start (API only, no GPU)

```bash
cd nexus_deepstream
poetry install
# Windows PowerShell:
$env:NEXUS_DS_DATA_DIR="./data"
poetry run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://127.0.0.1:8080 — add cameras and webhooks.

Pipeline stays idle without DeepStream (`pyservicemaker`); API/UI still work. GPU pipeline + ring-buffer run in a separate process:

```bash
poetry run python -m app.video
```

## Frontend (Vue)

UI lives in `frontend/` (Vue 3 + Vite). Locally FastAPI can serve `frontend/dist`. In Docker the UI is built into the **nginx** image.

```bash
cd frontend
npm install
npm run build
```

Dev with hot reload (proxy to API on :8080):

```bash
# terminal 1: API
poetry run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
# terminal 2: Vue
cd frontend && npm run dev
```

Open http://127.0.0.1:5173

## GPU container (Docker Compose)

1. Optionally `cp .env.example .env` and adjust ports/paths.
2. Build and run:

```bash
docker compose up --build -d
```

First boot of **video** runs `shell/video-boot.sh`, which calls `models/yolo11n/prepare.sh` if `yolo11n.onnx` is missing (download weights, export ONNX, compile the DeepStream parser). Needs internet and can take several minutes. You can also copy an already prepared tree into `models/yolo11n` (see `models/README.md`).

nginx (UI + `/api` proxy): http://127.0.0.1:8080

Requires NVIDIA Container Toolkit (`gpus: all` on **video**). nginx is the public entry; the API and video containers are internal.

## Local RTSP test source

MediaMTX + ffmpeg. Without a clip it uses `testsrc`; with a file it loops that video.

Put an MP4 here (H.264 preferred):

```text
deploy/rtsp-test/video/cam1.mp4
```

Then restart the publisher:

```bash
docker compose -f docker-compose.rtsp-test.yml up -d
# or: sh shell/rtsp-test-up.sh
```

Together with the GPU stack (video container can pull `mediamtx` by hostname):

```bash
docker compose -f docker-compose.yml -f docker-compose.rtsp-test.yml up -d
```

| URL | Use |
|-----|-----|
| `rtsp://127.0.0.1:8554/cam1` | VLC / ffplay / camera on the host |
| `http://127.0.0.1:8888/cam1/` | HLS in the browser |
| `http://127.0.0.1:8889/cam1/` | WebRTC in the browser |
| `rtsp://mediamtx:8554/cam1` | `Camera.rtsp_url` from the **video** container |

Stop: `docker compose -f docker-compose.rtsp-test.yml down`

Publisher knobs: `RTSP_TEST_SIZE` (default `1280x720`), `RTSP_TEST_FPS` (default `25`). Extra path `cam2` is reserved in `deploy/rtsp-test/mediamtx.yml` for a second ffmpeg if you need it.

Register two test cameras (`rtsp_test_1`, `rtsp_test_2`) on that stream:

```bash
python deploy/rtsp-test/seed-cameras.py
# GPU stack: python deploy/rtsp-test/seed-cameras.py --rtsp-url rtsp://mediamtx:8554/cam1
```

If the console already has users, pass `--login` / `--password` (webhook Basic). First boot with an empty users table needs no auth.

Postgres stores cameras, users, webhooks, trigger history, and the outbound job queue. Schema is applied with Alembic on **API** startup. `NEXUS_DS_DATABASE_URL` is required. There is no `cameras.json`.

## Production stack

Compose runs: **Postgres 16** → **PgBouncer** → **MinIO** → **API** (slim Python image, FastAPI) → **video** (DeepStream + rtsp_writer ring-buffer, GPU) → **nginx** (SPA + reverse proxy).

The API talks to Postgres through PgBouncer. Migrations use `NEXUS_DS_DATABASE_MIGRATE_URL` straight to `postgres` (DDL is not safe in transaction pooling).

Keep **one** worker in the video container. The DeepStream pipeline lives in that process; extra workers would start extra GPU pipelines.

API and video share `/data/nexus_deepstream` (settings.json + ring-buffer segments). The API notifies video at `NEXUS_DS_VIDEO_URL` when cameras/settings change. Internal video control (`:8081`) requires `NEXUS_DS_VIDEO_TOKEN` (`Authorization: Bearer …`). `/health` on `:8081` stays open for liveness.

Hot path (probe thread) never waits on the network or the database:

- Clip work and webhook enqueue go to an in-memory queue (`NEXUS_DS_SINK_WORKERS`). Delivery is a Postgres job queue with backoff and a dead-letter status.
- History inserts are batched (`NEXUS_DS_HISTORY_BATCH` / `NEXUS_DS_HISTORY_FLUSH_MS`) on a background writer. Reads do not commit.
- Camera list is cached (`NEXUS_DS_CAMERA_CACHE_MS`) and invalidated on write.

See `.env.example` for pool, queue, and cache knobs.

## API (for Django)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/health` | node status |
| GET | `/api/v1/cameras` | list cameras (`q`, `enabled`, `since`, `until`, `cursor`, `limit`; omit `limit` for the full list) |
| GET | `/api/v1/cameras/{id}` | one camera |
| POST | `/api/v1/cameras` | upsert one camera (`201` created / `200` updated). Aliases: `camera_id`, `rtsp_url`, `uri` |
| PUT | `/api/v1/cameras/{id}` | upsert by id (creates if missing) |
| PATCH | `/api/v1/cameras/{id}` | partial update |
| DELETE | `/api/v1/cameras/{id}` | remove |
| GET/PUT | `/api/v1/settings` | node settings |
| GET | `/api/v1/video/health` | GPU pipeline + per-camera ring-buffer health |
| GET/POST | `/api/v1/webhooks` | webhook list / create `{name, url, enabled, login, password, timeout_sec, max_retries}` |
| PUT/DELETE | `/api/v1/webhooks/{id}` | update / remove webhook |
| GET | `/api/v1/auth/session` | UI session status |
| POST | `/api/v1/auth/login` | UI session cookie (`email` + `password`; first user also sends `password_confirm`) |
| POST | `/api/v1/auth/logout` | clear UI cookie |
| GET | `/api/v1/users` | list console users (`q`, `since`, `until`, `cursor`, `limit`) |
| POST | `/api/v1/users` | create user `{email, password, name}` |
| DELETE | `/api/v1/users/{id}` | remove user |
| GET | `/api/v1/history/triggers` | trigger history page `{items, next_cursor}` |
| GET | `/api/v1/history/triggers/{event_id}` | one event + full payload |
| GET | `/api/v1/history/triggers/{event_id}/clip` | refresh MinIO presign |
| POST | `/api/v1/history/triggers/{event_id}/resend` | enqueue payload to all enabled webhooks |
| GET | `/api/v1/history/sends` | HTTP attempt history |
| GET | `/api/v1/history/outbound` | webhook job queue (`status=dead` for failures) |
| POST | `/api/v1/history/outbound/{id}/retry` | reset a job and send again |

If a webhook has a login and password, Campus sends them on the inbound camera API as HTTP Basic (`Authorization: Basic base64(login:password)`). The Vue UI logs in with email/password and uses an httpOnly cookie. The first visit with an empty `users` table creates the initial operator.

Django (or any other service) owns the camera on its side, then **pushes** it to this node:

```http
POST /api/v1/cameras
Authorization: Basic base64(login:password)
Content-Type: application/json

{
  "id": "cam_gate",
  "name": "Калитка",
  "rtsp_url": "rtsp://user:pass@10.0.0.12/stream1",
  "enabled": true,
  "external_id": "42"
}
```

`main_uri`, `uri`, and `rtsp_url` are the same field. The node also answers `GET /api/v1/cameras` so Campus can import like a SmartBox `channel/list`. Outbound webhooks are the other direction: this node POSTs trigger payloads to Django.

### Trigger payload (POST to each webhook)

Stable contract. `clip` and `video_url` are always present (empty strings if there is no file, e.g. `stream_silent`):

```json
{
  "event_id": "...",
  "category": "incident",
  "camera_id": "cam_xxx",
  "camera_name": "Gate",
  "trigger_type": "presence|convergence|vif|stream_silent",
  "trigger_time": "ISO-8601",
  "pre_s": 5,
  "post_s": 15,
  "evidence": {},
  "node_id": "ds-1",
  "model_versions": {"detector": "yolo11n", "first_line": "nexus_deepstream"},
  "clip": {
    "url": "http://127.0.0.1:9200/incidents/incidents/ingest/...?X-Amz-...",
    "bucket": "incidents",
    "key": "incidents/ingest/<date>/<camera>/<hour>/<event_id>.mp4"
  },
  "video_url": "http://127.0.0.1:9200/incidents/incidents/ingest/...?X-Amz-...",
  "video_bucket": "incidents",
  "video_key": "incidents/ingest/<date>/<camera>/<hour>/<event_id>.mp4"
}
```

Failed deliveries retry with backoff, then sit in the dead-letter queue until resend from history.

On an incident trigger the node waits `post_s`, concatenates ring-buffer segments covering `[trigger - pre_s, trigger + post_s]`, uploads the MP4 to MinIO, then enqueues POSTs. `stream_silent` skips the clip. The ring-buffer (`gst-launch` + `splitmuxsink`, ~3s segments) runs 24/7 for enabled RTSP cameras.

## Multi-node with one Django

1. Deploy node A (`node_id=ds-1`) and node B (`node_id=ds-2`).
2. On each node add a webhook (URL + login/password for inbound camera API) → same Campus ingest endpoint.
3. Campus creates/updates a camera locally, then `POST/PUT /api/v1/cameras` on the chosen node. Campus can also `GET /api/v1/cameras` to import.
4. Later in Campus: model `DeepStreamNode` + import cameras (create/update) + reject if camera already on another node.

## Move to its own git repo

This folder is self-contained. Copy `nexus_deepstream/` out and `git init`.
Campus can keep using the HTTP cameras/triggers contract without importing this package.
