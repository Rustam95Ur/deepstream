<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, api } from "../api";
import { enabledCount, flash, store } from "../store";
import { triggerLabel } from "../schoolAlgorithms";
import type { Camera, OutboundJob, TriggerEvent, VideoHealth, Webhook } from "../types";

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

function ringLabel(cameraId: string) {
  if (!isRtsp(store.cameras.find((c) => c.id === cameraId)?.main_uri || "")) return "не RTSP";
  const row = ringOf(cameraId);
  if (!health.value?.ring_running || !row) return "нет записи";
  if (!row.alive) return "упал";
  if (row.stalled) return "застой";
  return "живой";
}

function pipeReason(cam: Camera) {
  if (pipelineIds.value.has(cam.id)) return "";
  return skipById.value.get(cam.id) || (cam.enabled ? "не в текущем графе" : "выключена");
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
        <p class="lede">Pipeline детекции и ring-buffer клипов — разные контуры.</p>
      </div>
      <div class="card-body">
        <div v-if="store.cameras.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Камера</th>
                <th>URI</th>
                <th>Pipeline</th>
                <th>Причина</th>
                <th>Ring-buffer</th>
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
                  <span
                    class="pill"
                    :class="pipelineIds.has(cam.id) ? 'pill-ok' : 'pill-err'"
                    :title="pipeReason(cam)"
                  >
                    {{ pipelineIds.has(cam.id) ? "в пайпе" : "нет" }}
                  </span>
                </td>
                <td class="reason-cell" :class="{ 'is-ok': pipelineIds.has(cam.id) }">
                  {{ pipeReason(cam) || "—" }}
                </td>
                <td>
                  <span
                    class="pill"
                    :class="ringLabel(cam.id) === 'живой' ? 'pill-ok' : 'pill-err'"
                    :title="ringOf(cam.id)?.last_error || ''"
                  >
                    {{ ringLabel(cam.id) }}
                  </span>
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
