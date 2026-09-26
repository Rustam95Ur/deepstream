# Refactoring plan — Nexus DeepStream

Дата снимка: 2026-09-26. Документ описывает **текущий** код и поэтапный рефакторинг без смены поведения (контракты Campus / DeepStream / billing сохраняются).

## Статус

| Фаза | Статус |
|------|--------|
| Phase 0 — Hygiene | **done** (2026-09-26) |
| Phase 1 — Split `webhooks.py` | **done** (2026-09-26) |
| Phase 2 — Config consolidation | **done** (2026-09-26) |
| Phase 3 — DS pipeline / ring modularize | **done** (2026-09-26) |
| Phase 4 — Thin API | **done** (2026-09-26) |
| Phase 5 — Billing boundary | **done** (2026-09-26) |
| Phase 6 — Campus contract | **done** (2026-09-26) |
| Phase 7 — Later | **done** (2026-09-26; httpx deferred) |

Сделано в Phase 0–1:
- `app/timeutil.py`, `app/env.py`
- `app/api/deps.py` (+ re-export в `app.api`)
- единый `video_token` в `video_auth`
- `HistoryWriter` стартует на API; dual `OutboundWorker` задокументирован
- пакет `app/webhooks/` (`models`, `repository`, `queue`, `delivery`, `worker`) со стабильным `__init__`

Сделано в Phase 2:
- `app/runtime_env.py` — boot-time knobs (ring/minio/db/sink/history/video); `get_runtime_env()`
- `trigger_thresholds`: `DEFAULT_THRESHOLD_PROFILES` + flat mirrors; canonical = `trigger_thresholds`
- `triggers_url` — seed-only; `LinkRow` больше не пишется (таблица legacy); `hmac_secret` unused
- compose: комментарий `pipeline` service ↔ role `video`; knobs в `.env.example`

Сделано в Phase 3:
- `ds/probe.py`, `ds/pgie_config.py`, `ds/pipeline_runner.py` + фасад `ds/pipeline.py`
- `ds/ring_config.py`, `ds/ring_worker.py`, `ds/ring_supervisor.py` + фасад `ds/ring_buffer.py`
- `ds/static_filter.py` — sticky/furniture filter (unit-testable без GPU)

Сделано в Phase 4:
- `app/services/history.py` — history / outbound queries + clip/resend/retry
- `app/services/cameras.py` — capacity, test-batch, CRUD, pipeline drop-reload
- тонкие роутеры `api/history.py`, `api/cameras.py`

Сделано в Phase 5:
- пакет `app/billing/` — `models`, `validate`, `state`, `runtime_lock`
- адаптеры `VideoLocalLock` / `ApiVideoClientLock` вместо ветки `NEXUS_DS_ROLE` в одной функции
- `docker_destroy` по-прежнему изолирован; фасад `app.billing` стабилен

Сделано в Phase 6:
- пакет `app/campus/` — `ingest`, `cameras` (CameraResolver), `urls` (public_clip_url)
- `ds/payload.py` — только internal payload; `to_smartbox_ingest` re-export
- history / clip_sink / delivery читают URL через `campus.urls`

Сделано в Phase 7:
- `app/schemas/` по доменам (`cameras`, `node`, `webhooks`, `history`, `users`) + фасад
- Alembic `0008_drop_links_hmac` — drop `links` + `webhooks.hmac_secret`
- `scripts/export_openapi.py` — выгрузка OpenAPI для фронта
- **отложено:** `httpx` (только после замера); автоген TS из OpenAPI

## Цели

- Разрезать god-модули, сохранив публичные фасады и импорты.
- Убрать дубли (`_utcnow`, `_aware`, `_env*`, `video_token`).
- Явно зафиксировать ownership процессов (API vs video).
- Утончить роутеры; вынести SQL/бизнес-логику в сервисы.
- Не трогать hot path probe без крайней нужды: clip/webhook/history остаются вне probe-потока.

## Не цели (в этом плане)

- Переписывать FastAPI на async DB / httpx «ради async».
- Менять SmartBox envelope и multipart `payload` + `video`.
- Переименовывать compose-сервисы без отдельного согласования.
- Генерировать OpenAPI → TS (можно позже, Phase 7).

## Архитектура (как есть)

| Процесс | Entry | Порт | Роль |
|---------|-------|------|------|
| **API** | `app.main:app` | 8080 | cameras, settings, webhooks, users, history, billing, public clips, SPA |
| **Video** | `app.video:app` | 8081 | DeepStream + ring-buffer; history writer; outbound worker |
| **nginx** | Docker | public 8080 | Vue + `/api` proxy |
| Postgres → PgBouncer | shared | — | ORM + job queue |
| MinIO | shared | — | MP4 инцидентов |

```
RTSP → [video] ring_buffer + pipeline.probe
         → TriggerEngine → AsyncSink → ClipSink / OutboundEnqueueSink
         → HistoryWriter + OutboundWorker → Campus

Django/UI → [api] FastAPI → Store / webhooks / billing
         → video_client → :8081 (reload, lock)
```

Два слоя настроек:

- UI/API: `NodeSettings` в `settings.json` (`Store`)
- Runtime DS: `AppConfig` / `TriggerConfig` / `PipelineConfig` (`app/ds/config.py` ← `app_config_from_settings`)

---

## Карта крупных модулей

| Файл | ~стр. | Проблема |
|------|------:|----------|
| `app/webhooks.py` | 605 | CRUD + queue + delivery + worker в одном файле |
| `app/ds/pipeline.py` | 556 | probe + YAML PGIE/source + `run_pipeline` / EOS |
| `app/ds/ring_buffer.py` | 540 | env-кнобы + worker + supervisor + manager |
| `app/schemas.py` | 447 | все DTO; тяжёлые alias-валидаторы камер |
| `app/ds/triggers.py` | 416 | плотный, но цельный; кандидат на вынос static filter |
| `app/billing.py` | 372 | validate + disk + FastAPI guard + runtime lock + destroy |
| `app/ds/payload.py` | 349 | Campus contract + DB lookup камеры |
| `app/minio_store.py` | 339 | storage + public URL heuristics для Campus |
| `app/api/history.py` | 263 | толстый роутер с SQL |
| `app/api/__init__.py` | ~72 | на самом деле auth deps, не package API |

---

## Запах / coupling

### God modules

1. **`webhooks.py`** — `list/create/update/delete`, `seed_webhooks_from_settings`, `enqueue_payload` / `resend_event` / `retry_job`, `_deliver` / `process_job` / `_CLAIM_SQL`, `OutboundWorker`.
2. **`ds/pipeline.py`** — metadata helpers, `write_pgie_config` / `write_source_config`, `run_pipeline` с EOS/reload.
3. **`ds/ring_buffer.py`** — десятки `NEXUS_DS_RING_*`, `IncidentRingBufferWorker`, supervisor, `RingBufferManager`.
4. **`billing.py`** — ветвление API/video через `NEXUS_DS_ROLE` внутри lock/unlock.

### Смешанные ответственности

| Симптом | Где |
|---------|-----|
| Clip sink делает history + MinIO + gate webhook | `ds/sinks/clip_sink.py` |
| Payload ходит в БД | `ds/payload.py` (`_lookup_local_camera_id`) |
| Outbound стартует в API **и** video | `main.py`, `video.py` (`SKIP LOCKED` — ок, ownership неясен) |
| HistoryWriter только на video | `video.py`; API `record_send` может писать в незапущенный writer |
| `triggers_url` + seed + `LinkRow` | двойной источник правды; `hmac_secret` почти мёртв |
| Auth в `api/__init__.py` | путаница имени пакета |

### Дубли

- `_aware` — `api/cameras.py`, `api/history.py`, `api/users.py`
- `_utcnow` — `webhooks`, `storage`, `history`, `users`, `models`, `log_buffer`
- `_env` / `_env_int` — `db`, `history`, `minio_store`, `ring_buffer`, `async_sink`
- `video_token()` — `video_client.py` **и** `video_auth.py`
- `_require_db()` — `api/webhooks.py`, `api/history.py`
- Camera aliases — `CameraIn` / `CameraPatch` в `schemas.py`
- Пороги триггеров — flat поля `NodeSettings` **и** `trigger_thresholds`

### Config sprawl

Env читается локально в модулях, а не только из `EnvBootstrap`: DB pool, ring, MinIO/public URL, sink/history queues, video host/token, billing URL override.

### Sync / naming

- FastAPI `async` lifespan, остальной I/O sync (SQLAlchemy, urllib, `http.client`, threads) — нормально; `AsyncSink` = thread pool, не asyncio.
- Внутренне стандартизировать URI камеры на `rtsp_url`; aliases оставить только на границе API.

---

## Фазы

Каждая фаза оставляет систему рабочей: API + video + Postgres + MinIO + GPU pipeline.

### Phase 0 — Hygiene (без смены поведения) ✅

1. `app/timeutil.py` — `utcnow`, `aware`; заменить копии.
2. `app/env.py` — `env_str` / `env_int` / `env_float`; заменить локальные `_env*`.
3. Auth: `app/api/__init__.py` → `app/api/deps.py` (re-export при необходимости).
4. Один `video_token()` — `video_auth.py`; `video_client` импортирует оттуда.
5. Ownership: задокументировать; **запустить `HistoryWriter` на API** или не вызывать `record_send` без writer (корректность).
6. Зафиксировать в комментарии/ADR: dual `OutboundWorker` намеренно (claim + `SKIP LOCKED`).

**Критерий готовности:** импорты зелёные; smoke API login + cameras list; video `/health`.

### Phase 1 — Split `webhooks.py` (высокий ROI) ✅

Пакет `app/webhooks/`:

| Модуль | Содержимое |
|--------|------------|
| `models.py` | dataclass `Webhook`, `_from_row` |
| `repository.py` | CRUD, `authenticate_webhook_login`, seed |
| `queue.py` | `enqueue_payload`, `resend_event`, `retry_job` |
| `delivery.py` | clip bytes, `_deliver`, `process_job`, claim SQL |
| `worker.py` | `OutboundWorker` |
| `__init__.py` | стабильные re-export для sinks / API |

**Тест-фокус:** enqueue → claim → multipart; resend из history; skip при invalid license.

### Phase 2 — Config consolidation ✅

1. Расширить `EnvBootstrap` / `RuntimeEnv`: ring, minio, db-pool, sink, history — читать на boot.
2. Свести flat trigger fields к `trigger_thresholds` (одно поколение sync-валидаторов).
3. Решить судьбу `triggers_url` / `LinkRow` / `hmac_secret` (оставить seed-only или Alembic drop).
4. Документировать `pipeline` container ↔ role `video` без обязательного rename.

### Phase 3 — DS modularize (GPU-sensitive) ✅

1. `pipeline.py` → `probe.py` + `pgie_config.py` + `pipeline_runner.py`; сигнатура `run_pipeline` для `PipelineManager` без изменений.
2. `ring_buffer.py` → config / worker / supervisor; фасад `get_ring_buffer()` сохранить.
3. Опционально: sticky/furniture → `ds/static_filter.py` для unit-тестов без GPU.

**Ограничения:** один worker-процесс; не `chdir`/`run_pipeline` из API image; probe не блокировать.

### Phase 4 — Thin API ✅

1. History queries → `app/services/history.py` (или `history_queries.py`).
2. Camera service: capacity, test-batch, reload notify рядом со `Store`.
3. Роутеры: validate → service → schema.

### Phase 5 — Billing boundary ✅

1. `billing/validate.py`, `billing/state.py`, `billing/runtime_lock.py`.
2. Адаптеры lock: local (video) vs `video_client` (API) вместо ветки `NEXUS_DS_ROLE` внутри одной функции.
3. `docker_destroy` остаётся изолированным.

### Phase 6 — Campus contract ✅

1. SmartBox shaping — один модуль (`ds/payload.py` или `campus/ingest.py`).
2. `CameraResolver` protocol вместо прямого DB в payload.
3. Public clip URL + multipart delivery читают один builder URL.

### Phase 7 — Later ✅ (частично)

1. ~~`httpx` для outbound/billing~~ — **отложено** до замера latency/ошибок.
2. `schemas/` по доменам — done.
3. Alembic drop мёртвых колонок (`links`, `hmac_secret`) — done (`0008`).
4. Sync thresholds с frontend через OpenAPI — экспорт `scripts/export_openapi.py`; codegen TS по желанию.

---

## Приоритеты

| P | Действие |
|---|----------|
| P0 | HistoryWriter ownership на API; ADR по dual outbound |
| P1 | Split `webhooks.py` за стабильным `__init__` |
| P2 | `timeutil` / `env` / `api/deps` / единый `video_token` |
| P3 | Механический split `pipeline.py` / `ring_buffer.py` |
| P4 | Thin routers; billing adapters |
| P5 | Config: thresholds / LinkRow / hmac_secret |

---

## Риски и инварианты

### GPU / DeepStream

- API image slim — не импортировать `run_pipeline` / `pyservicemaker` в API-пути.
- `os.chdir(yolo_dir)` в `run_pipeline` — process-global; второй pipeline запрещён.
- EOS/reload в `run_pipeline` — зона change-control.
- Hot path: только `AsyncSink` + batched history + outbound queue.

### Docker / ops

- Shared volume: `NEXUS_DS_DATA_DIR`, ring segments — пути должны совпадать у api и video.
- `NEXUS_DS_PUBLIC_URL` / `advertised_public_base` — регрессии ломают скачивание клипа Campus.
- `stolen_key` + destroy — тестировать только в изолированном compose.

### DB

- Миграции только на API через `NEXUS_DS_DATABASE_MIGRATE_URL` (не через PgBouncer).
- Transaction pooling: короткие `session_scope`; claim SQL и статусы `outbound_jobs` менять вместе с миграциями.

### Внешние контракты

- Multipart `payload` + `video`; JSON для `stream_silent`.
- Inbound cameras: Basic / session / first-boot.
- License invalid: pipeline/ring stop; API 403 кроме login/settings/health; `/health` всегда 200 с `license_valid`.

---

## Чеклист перед мержем фазы

- [ ] `poetry run` API поднимается; `GET /api/v1/health`
- [ ] Video `/health` (или mock без GPU) без traceback
- [ ] Импорты sinks/API после split webhooks не сломаны
- [ ] Enqueue → dead-letter / retry путь не регрессировал
- [ ] Billing lock: invalid key останавливает pipeline с обеих ролей
- [ ] Нет новых env без записи в `.env.example`

---

## Порядок работ агенту

1. Начать с Phase 0 + Phase 1.
2. Каждый PR = одна фаза (или подшаг god-module split).
3. После разреза — только re-export в старых путях на 1–2 релиза, затем убрать.
4. GPU-файлы (Phase 3) — отдельный PR, smoke на машине с DeepStream.
