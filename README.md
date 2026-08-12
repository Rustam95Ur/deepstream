# Nexus DeepStream

Standalone DeepStream first-line node: FastAPI control plane + GPU pipeline.
One Django Campus can attach multiple nodes (different GPUs / machines).

## Features

- Local camera registry (`GET/POST/DELETE /api/v1/cameras`) — Django imports like SmartBox
- Settings UI at `/` (Vue SPA behind nginx in Docker)
- Trigger sink: HTTP POST to `triggers_url`
- Optional pull from `cameras_url` on an interval
- Pipeline runs in a background thread when `pyservicemaker` is available

## Quick start (API only, no GPU)

```bash
cd nexus_deepstream
poetry install
# Windows PowerShell:
$env:NEXUS_DS_DATA_DIR="./data"
poetry run python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://127.0.0.1:8080 — add cameras, set `triggers_url`.

Pipeline stays idle without DeepStream (`pyservicemaker`); API/UI still work.

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

1. Copy prepared YOLO tree into `models/yolo11n` (see `models/README.md`).
2. Optionally `cp .env.example .env` and adjust ports/paths.
3. Build and run:

```bash
docker compose up --build -d
```

nginx (UI + `/api` proxy): http://127.0.0.1:8080

Requires NVIDIA Container Toolkit (`gpus: all`). The DeepStream API container is internal; nginx is the public entry.

Postgres stores cameras, users, integration URLs (`cameras_url` / `triggers_url`), trigger history, and outbound send history. Schema is applied with Alembic on API startup. `NEXUS_DS_DATABASE_URL` is required. There is no `cameras.json`.

## Production stack

Compose runs four services: **Postgres 16** (tuned WAL/buffers) → **PgBouncer** (transaction pool) → **API** (one uvicorn worker, GPU pipeline in-process) → **nginx** (SPA + keep-alive reverse proxy).

The API talks to Postgres through PgBouncer (internal `:5432` on the `pgbouncer` service). Migrations use `NEXUS_DS_DATABASE_MIGRATE_URL` straight to the `postgres` service (DDL is not safe in transaction pooling).

Keep **one** uvicorn worker. The DeepStream pipeline lives in that process; extra workers would start extra GPU pipelines.

Hot path (probe thread) never waits on the network or the database:

- Trigger HTTP goes to an in-memory queue and 4 worker threads (`NEXUS_DS_SINK_WORKERS`). HTTP uses keep-alive. If the queue is full, the event is dropped and logged.
- History inserts are batched (`NEXUS_DS_HISTORY_BATCH` / `NEXUS_DS_HISTORY_FLUSH_MS`) on a background writer. Reads do not commit.
- Camera list is cached (`NEXUS_DS_CAMERA_CACHE_MS`) and invalidated on write.

See `.env.example` for pool, queue, and cache knobs.

## API (for Django)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/health` | node status |
| GET | `/api/v1/cameras` | list cameras (`q`, `enabled`, `since`, `until`, `cursor`, `limit`; omit `limit` for the full list) |
| POST | `/api/v1/cameras` | upsert camera `{id, name, main_uri, enabled}` |
| DELETE | `/api/v1/cameras/{id}` | remove |
| GET/PUT | `/api/v1/settings` | node settings |
| POST | `/api/v1/cameras-pull` | pull from `cameras_url` |
| GET | `/api/v1/auth/session` | UI session status |
| POST | `/api/v1/auth/login` | UI session cookie (`email` + `password`; first user also sends `password_confirm`) |
| POST | `/api/v1/auth/logout` | clear UI cookie |
| GET | `/api/v1/users` | list console users (`q`, `since`, `until`, `cursor`, `limit`) |
| POST | `/api/v1/users` | create user `{email, password, name}` |
| DELETE | `/api/v1/users/{id}` | remove user |
| GET | `/api/v1/history/triggers` | trigger history page `{items, next_cursor}` (`since`, `until`, `camera_id`, `trigger_type`, `category`, `event_id`, `cursor`, `limit`) |
| GET | `/api/v1/history/sends` | HTTP send history page `{items, next_cursor}` (`since`, `until`, `status`, `event_id`, `sink`, `cursor`, `limit`) |

If `api_token` is set in settings, send `Authorization: Bearer <token>` for machine access. The Vue UI logs in with email/password and uses an httpOnly cookie. The first visit with an empty `users` table creates the initial operator.

### Trigger payload (POST to `triggers_url`)

Compatible with Campus DeepStream contract:

```json
{
  "event_id": "...",
  "category": "incident",
  "camera_id": "cam_xxx",
  "trigger_type": "presence|convergence|vif|stream_silent",
  "trigger_time": "ISO-8601",
  "pre_s": 5,
  "post_s": 15,
  "evidence": {},
  "node_id": "ds-1",
  "model_versions": {"detector": "yolo11n", "first_line": "nexus_deepstream"}
}
```

## Multi-node with one Django

1. Deploy node A (`node_id=ds-1`) and node B (`node_id=ds-2`).
2. On each node set `triggers_url` → same Campus ingest endpoint.
3. Add cameras per node (UI/API) **or** set `cameras_url` filtered by `node_id`.
4. Later in Campus: model `DeepStreamNode` + import cameras (create/update) + reject if camera already on another node.

## Move to its own git repo

This folder is self-contained. Copy `nexus_deepstream/` out and `git init`.
Campus can keep using the HTTP cameras/triggers contract without importing this package.
