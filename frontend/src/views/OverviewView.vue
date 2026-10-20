<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, api } from "../api";
import { enabledCount, flash, store } from "../store";
import { triggerLabel } from "../schoolAlgorithms";
import type { Camera, CameraStream, OutboundJob, TriggerEvent, VideoHealth, Webhook } from "../types";

const router = useRouter();
const health = ref<VideoHealth | null>(null);
const triggers = ref<TriggerEvent[]>([]);
const hooks = ref<Webhook[]>([]);
const deadJobs = ref<OutboundJob[]>([]);
const playing = ref<TriggerEvent | null>(null);
const playUrl = ref("");
const busyId = ref("");
let timer: ReturnType<typeof setInterval> | null = null;

const pipelineIds = computed(() => {
  const fromHealth = health.value?.pipeline?.camera_ids;
  const ids = fromHealth?.length ? fromHealth : store.worker?.camera_ids || [];
  return new Set(ids);
});
const skipById = computed(() => {
  const rows = health.value?.pipeline?.skipped || store.worker?.skipped || [];
  return new Map(rows.map((row) => [row.camera_id, row.reason]));
});
const errorLog = computed(() => {
  const rows =
    health.value?.recent_errors ||
    health.value?.pipeline?.recent_errors ||
    store.worker?.recent_errors ||
    [];
  return rows.slice(0, 40);
});
const enabledHooks = computed(() => hooks.value.filter((h) => h.enabled));
const rtspCameras = computed(() =>
  store.cameras.filter((c) => c.enabled && isRtsp(c.main_uri)),
);

const ringReason = computed(() => {
  if (!health.value) return "нет связи с video-контейнером";
  if (!health.value.clip_record) return "запись клипов выключена в Связи";
  if (!health.value.gst_available) return "в контейнере нет gst-launch";
  if (!store.cameras.some((c) => c.enabled)) return "нет включённых камер";
  if (!rtspCameras.value.length) return "нет RTSP-потоков — ring-buffer пишет только rtsp://";
  if (!health.value.ring_running) return "recorder не запущен";
  const n = health.value.cameras.length;
  return n ? `пишет ${n} поток.` : "пишет сегменты";
});

function isRtsp(uri: string) {
  return uri.trim().toLowerCase().startsWith("rtsp://");
}

function ringOf(cameraId: string) {
  return health.value?.cameras.find((c) => c.camera_id === cameraId);
}

function streamOf(cameraId: string): CameraStream | undefined {
  return health.value?.streams?.find((row) => row.camera_id === cameraId);
}

function ageText(sec: number | null | undefined) {
  if (sec == null || Number.isNaN(sec)) return "";
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s} с`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m} мин ${rem} с` : `${m} мин`;
}

function explainGst(raw: string) {
  const text = raw.trim();
  if (!text) return "";
  const t = text.toLowerCase();
  if (t.includes("end-of-file") || t.includes("end of file")) return "камера закрыла RTSP";
  if (t.includes("parse error")) return "камера ответила не RTSP";
  if (t.includes("connection refused")) return "соединение отклонено";
  if (t.includes("timed out") || t.includes("timeout")) return "таймаут RTSP";
  if (t.includes("not found") || t.includes("404")) return "поток не найден";
  if (t.includes("no data")) return "источник не отдаёт кадры";
  if (t.includes("could not read") || t.includes("could not write") || t.includes("system error")) {
    return "нет связи с камерой";
  }
  return text.length > 180 ? `${text.slice(0, 177)}…` : text;
}

function pipeReason(cam: Camera) {
  if (pipelineIds.value.has(cam.id)) return "";
  return skipById.value.get(cam.id) || (cam.enabled ? "не в текущем графе" : "выключена");
}

function detectState(cam: Camera) {
  if (!health.value) return "down";
  if (!pipelineIds.value.has(cam.id)) return "out";
  return streamOf(cam.id)?.state || "unknown";
}

function detectLabel(cam: Camera) {
  switch (detectState(cam)) {
    case "live":
      return "кадры";
    case "starting":
      return "старт";
    case "waiting":
      return "ждёт";
    case "silent":
      return "молчит";
    case "closed":
      return "нет потока";
    case "down":
      return "нет связи";
    case "out":
      return "нет";
    default:
      return "нет данных";
  }
}

function detectClass(cam: Camera) {
  const state = detectState(cam);
  if (state === "live") return "pill-ok";
  if (state === "starting" || state === "waiting") return "pill-warn";
  if (state === "out" && !cam.enabled) return "pill-muted";
  return "pill-err";
}

function detectTitle(cam: Camera) {
  const problem = detectProblem(cam);
  if (problem) return problem;
  const age = ageText(streamOf(cam.id)?.last_frame_age_s);
  return age ? `последний кадр ${age} назад` : "";
}

function detectProblem(cam: Camera) {
  const state = detectState(cam);
  const age = ageText(streamOf(cam.id)?.last_frame_age_s);
  if (state === "down") return "нет связи с video-контейнером";
  if (state === "out") return pipeReason(cam);
  if (state === "starting") {
    const up = ageText(streamOf(cam.id)?.pipeline_uptime_s);
    return up
      ? `пайплайн ещё поднимается, кадров нет уже ${up}`
      : "пайплайн ещё поднимается, кадров нет";
  }
  if (state === "waiting") return "поток ещё открывается";
  if (state === "closed") return "кадров не было — RTSP не открылся";
  if (state === "silent") {
    return age
      ? `нет кадров ${age} — источник молчит, идёт переподключение`
      : "источник молчит, идёт переподключение";
  }
  if (state === "unknown") return "нет данных о кадрах";
  return "";
}

function ringKind(cameraId: string) {
  if (!health.value) return "down";
  if (!isRtsp(store.cameras.find((c) => c.id === cameraId)?.main_uri || "")) return "skip";
  if (!health.value.clip_record) return "off";
  const row = ringOf(cameraId);
  if (!health.value.ring_running || !row) return "absent";
  if (!row.alive) return "dead";
  if (row.stalled) return "stalled";
  return "live";
}

function ringLabel(cameraId: string) {
  switch (ringKind(cameraId)) {
    case "live":
      return "пишет";
    case "stalled":
      return "застой";
    case "dead":
      return "упал";
    case "skip":
      return "не RTSP";
    case "off":
      return "выкл";
    case "down":
      return "нет связи";
    default:
      return "нет записи";
  }
}

function ringClass(cameraId: string) {
  const kind = ringKind(cameraId);
  if (kind === "live") return "pill-ok";
  if (kind === "stalled" || kind === "off") return "pill-warn";
  if (kind === "skip") return "pill-muted";
  return "pill-err";
}

function ringProblem(cameraId: string) {
  const kind = ringKind(cameraId);
  const row = ringOf(cameraId);
  const why = explainGst(row?.last_error || "");
  const age = ageText(row?.last_segment_age_s);
  if (kind === "dead") {
    return why ? `запись упала: ${why}` : "запись упала";
  }
  if (kind === "stalled") {
    const stall = age ? `запись встала, сегмент ${age} назад` : "запись встала";
    return why ? `${stall}: ${why}` : stall;
  }
  if (kind === "absent" && isRtsp(store.cameras.find((c) => c.id === cameraId)?.main_uri || "")) {
    return "запись не запущена";
  }
  if (kind === "live" && row && row.restarts > 0) {
    return `запись идёт, перезапусков ${row.restarts}`;
  }
  return "";
}

function streamProblem(cam: Camera) {
  if (!cam.enabled) return pipeReason(cam) || "выключена";
  const parts = [detectProblem(cam), ringProblem(cam.id)].filter(Boolean);
  return parts.join(" · ");
}

function streamOk(cam: Camera) {
  return !streamProblem(cam);
}

function logTime(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("ru-RU");
}

function logLevel(level: string) {
  return (level || "WARN").toUpperCase();
}

function fmt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

function hasClip(row: TriggerEvent) {
  return Boolean(row.video_url || row.clip?.url || row.clip?.key || row.video_key);
}

function clipSkipReason(row: TriggerEvent) {
  const ev = row.evidence || {};
  const raw = ev.webhook_video_error || ev.clip_error;
  return typeof raw === "string" && raw.trim() ? raw.trim() : "";
}

async function loadAll() {
  const [h, t, w, d] = await Promise.all([
    api.videoHealth().catch(() => null),
    api.historyTriggers({ limit: 8 }).catch(() => ({ items: [] as TriggerEvent[] })),
    api.webhooks().catch(() => ({ items: [] as Webhook[] })),
    api.historyOutbound({ status: "dead", limit: 5 }).catch(() => ({ items: [] as OutboundJob[] })),
  ]);
  health.value = h;
  triggers.value = t.items;
  hooks.value = w.items;
  deadJobs.value = d.items;
}

async function openClip(row: TriggerEvent) {
  playing.value = row;
  playUrl.value = `/api/v1/public/clips/${encodeURIComponent(row.event_id)}.mp4`;
}

function closeClip() {
  playing.value = null;
  playUrl.value = "";
}

async function retry(job: OutboundJob) {
  busyId.value = job.id;
  try {
    await api.retryOutbound(job.id);
    flash("Повтор поставлен в очередь");
    deadJobs.value = (await api.historyOutbound({ status: "dead", limit: 5 })).items;
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось повторить";
  } finally {
    busyId.value = "";
  }
}

onMounted(() => {
  void loadAll();
  timer = setInterval(() => {
    void loadAll();
  }, 8000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div v-if="store.settings && store.worker" class="stack-lg">
    <div class="stats">
      <article class="card stat-card">
        <div class="card-head">
          <h2>Pipeline</h2>
        </div>
        <div class="stat-body">
          <span class="stat-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </span>
          <p class="stat-v" :class="store.worker.running ? 'ok' : 'muted'">
            {{ store.worker.running ? "работает" : "остановлен" }}
          </p>
          <span
            class="badge"
            :class="store.worker.running ? (store.worker.available ? 'badge-ok' : 'badge-warn') : 'badge-muted'"
          >
            {{
              store.worker.running
                ? (store.worker.available ? "онлайн" : "нет GPU")
                : "стоп"
            }}
          </span>
        </div>
        <div class="card-foot">
          <span>{{ store.worker.detail || "Нет статуса" }}</span>
        </div>
      </article>

      <article class="card stat-card">
        <div class="card-head">
          <h2>Камеры</h2>
        </div>
        <div class="stat-body">
          <span class="stat-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="7" width="13" height="11" rx="2" stroke="currentColor" stroke-width="1.8"/>
              <path d="M16 11.5 21 9v8l-5-2.5v-3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            </svg>
          </span>
          <p class="stat-v">{{ enabledCount }}</p>
          <span class="badge badge-primary">{{ store.cameras.length }} всего</span>
        </div>
        <div class="card-foot">
          <span>{{ rtspCameras.length }} RTSP · {{ store.cameras.length - rtspCameras.length }} без rtsp://</span>
        </div>
      </article>

      <article class="card stat-card">
        <div class="card-head">
          <h2>Ring-buffer</h2>
        </div>
        <div class="stat-body">
          <span class="stat-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/>
              <path d="M12 8v4l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
          </span>
          <p class="stat-v" :class="health?.ring_running ? 'ok' : 'muted'">
            {{ health?.ring_running ? "пишет" : (health ? "стоп" : "—") }}
          </p>
          <span class="badge" :class="health?.gst_available ? 'badge-ok' : 'badge-warn'">
            {{ health?.gst_available ? "gst" : "нет gst" }}
          </span>
        </div>
        <div class="card-foot">
          <span>{{ ringReason }}</span>
        </div>
      </article>
    </div>

    <section class="card">
      <div class="card-head">
        <h2>Потоки</h2>
        <p class="lede">По каждой камере: идут ли кадры в детекцию и жива ли запись. Обновляется каждые 8 с.</p>
      </div>
      <div class="card-body">
        <div v-if="store.cameras.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Камера</th>
                <th>URI</th>
                <th>Детекция</th>
                <th>Запись</th>
                <th>Что не так</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="cam in store.cameras" :key="cam.id">
                <td>
                  {{ cam.name || cam.id }}
                  <span v-if="!cam.enabled" class="pill">выкл</span>
                </td>
                <td class="uri">{{ cam.main_uri || "—" }}</td>
                <td>
                  <span class="pill" :class="detectClass(cam)" :title="detectTitle(cam)">
                    {{ detectLabel(cam) }}
                  </span>
                </td>
                <td>
                  <span
                    class="pill"
                    :class="ringClass(cam.id)"
                    :title="ringOf(cam.id)?.last_error || ''"
                  >
                    {{ ringLabel(cam.id) }}
                  </span>
                </td>
                <td class="reason-cell" :class="{ 'is-ok': streamOk(cam) }">
                  {{ streamProblem(cam) || "поток в порядке" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Камер нет</p>
          <p class="lede">Добавьте поток, чтобы pipeline и клипы заработали.</p>
        </div>
      </div>
      <div class="card-foot end">
        <button type="button" class="ghost" @click="router.push({ name: 'cameras' })">К камерам</button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Лог ошибок</h2>
        <p class="lede">WARNING и ERROR с video-процесса и ring-buffer. Обновляется вместе со статусом.</p>
      </div>
      <div class="card-body">
        <div v-if="errorLog.length" class="log-list" role="log" aria-live="polite">
          <article
            v-for="(row, idx) in errorLog"
            :key="`${row.ts || ''}-${idx}`"
            class="log-row"
            :class="{ 'is-error': logLevel(row.level).startsWith('ERR') }"
          >
            <p class="log-meta">
              <span>{{ logTime(row.ts) || "—" }}</span>
              <span>{{ logLevel(row.level) }}</span>
              <span v-if="row.logger">{{ row.logger }}</span>
            </p>
            <p class="log-msg">{{ row.message }}</p>
          </article>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Ошибок нет</p>
          <p class="lede">Как только пайплайн или recorder упадут — строка появится здесь.</p>
        </div>
      </div>
    </section>

    <div class="split-2">
      <section class="card">
        <div class="card-head">
          <h2>Последние сработки</h2>
          <p class="lede">Что нода уже поймала. Клип — если ring-buffer успел записать.</p>
        </div>
        <div class="card-body">
          <div v-if="triggers.length" class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Камера</th>
                  <th>Тип</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in triggers" :key="row.event_id">
                  <td>{{ fmt(row.created_at) }}</td>
                  <td>{{ row.camera_name || row.camera_id }}</td>
                  <td>{{ triggerLabel(row.trigger_type) }}</td>
                  <td class="td-action">
                    <button v-if="hasClip(row)" type="button" class="ghost" @click="openClip(row)">
                      Смотреть
                    </button>
                    <span v-else class="muted" :title="clipSkipReason(row)">{{ clipSkipReason(row) || "нет клипа" }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty">
            <p class="empty-title">Сработок ещё нет</p>
          </div>
        </div>
        <div class="card-foot end">
          <button type="button" class="ghost" @click="router.push({ name: 'history' })">В историю</button>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>Доставка</h2>
          <p class="lede">Webhook’и и очередь неудач.</p>
        </div>
        <div class="card-body">
          <p class="delivery-line">
            <strong>{{ enabledHooks.length }}</strong> вкл.
            <span class="muted">из {{ hooks.length }}</span>
            <span
              class="pill"
              :class="deadJobs.length ? 'pill-err' : 'pill-ok'"
            >
              {{ deadJobs.length ? `${deadJobs.length} неудач` : "очередь чистая" }}
            </span>
          </p>
          <div v-if="deadJobs.length" class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Ошибка</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in deadJobs" :key="job.id">
                  <td class="uri">{{ job.url }}</td>
                  <td class="uri">{{ job.last_error || "—" }}</td>
                  <td class="td-action">
                    <button type="button" class="ghost" :disabled="busyId === job.id" @click="retry(job)">
                      Ещё раз
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else-if="!hooks.length" class="empty">
            <p class="empty-title">Webhook’ов нет</p>
            <p class="lede">События останутся только в истории.</p>
          </div>
        </div>
        <div class="card-foot end">
          <button type="button" class="ghost" @click="router.push({ name: 'ingest' })">К связи</button>
        </div>
      </section>
    </div>

    <div v-if="playing" class="modal-scrim" @click.self="closeClip">
      <section class="card modal modal-video">
        <div class="card-head">
          <h2>{{ playing.camera_name || playing.camera_id }} · {{ triggerLabel(playing.trigger_type) }}</h2>
          <p class="lede">{{ playing.event_id }}</p>
        </div>
        <div class="card-body">
          <video v-if="playUrl" class="clip-player" :src="playUrl" controls autoplay />
          <p v-else class="lede">URL клипа недоступен.</p>
        </div>
        <div class="card-foot end">
          <button type="button" class="ghost" @click="closeClip">Закрыть</button>
        </div>
      </section>
    </div>
  </div>
</template>
