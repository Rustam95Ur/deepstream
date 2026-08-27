<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import DateRangeField from "../components/DateRangeField.vue";
import Field from "../components/Field.vue";
import Pager from "../components/Pager.vue";
import { ApiError, api } from "../api";
import { HISTORY_PAGE_SIZE, useCursorPage } from "../cursorPage";
import { flash, store } from "../store";
import { triggerLabel, TRIGGER_LABELS } from "../schoolAlgorithms";
import type { HistoryQuery, OutboundJob, SendEvent, TriggerEvent } from "../types";

const TRIGGER_TYPES = [
  { value: "", label: "Все типы" },
  ...Object.entries(TRIGGER_LABELS).map(([value, label]) => ({ value, label })),
];

const STATUSES = [
  { value: "", label: "Все статусы" },
  { value: "ok", label: "Успех" },
  { value: "error", label: "Ошибка" },
  { value: "skipped", label: "Пропуск" },
];

const JOB_STATUSES = [
  { value: "", label: "Все" },
  { value: "pending", label: "Ожидает" },
  { value: "retrying", label: "Повтор" },
  { value: "ok", label: "Успех" },
  { value: "dead", label: "Неудачи" },
];

const filters = reactive({
  from: "",
  to: "",
  camera_id: "",
  trigger_type: "",
  status: "",
  job_status: "dead",
  event_id: "",
});

const triggers = ref<TriggerEvent[]>([]);
const sends = ref<SendEvent[]>([]);
const jobs = ref<OutboundJob[]>([]);
const loadingTriggers = ref(false);
const loadingSends = ref(false);
const loadingJobs = ref(false);
const playing = ref<TriggerEvent | null>(null);
const playUrl = ref("");
const busyId = ref("");

const {
  cursor: triggerCursor,
  canPrev: triggerCanPrev,
  canNext: triggerCanNext,
  resetPage: resetTriggerPage,
  setNext: setTriggerNext,
  goNext: goTriggerNext,
  goPrev: goTriggerPrev,
} = useCursorPage();
const {
  cursor: sendCursor,
  canPrev: sendCanPrev,
  canNext: sendCanNext,
  resetPage: resetSendPage,
  setNext: setSendNext,
  goNext: goSendNext,
  goPrev: goSendPrev,
} = useCursorPage();
const {
  cursor: jobCursor,
  canPrev: jobCanPrev,
  canNext: jobCanNext,
  resetPage: resetJobPage,
  setNext: setJobNext,
  goNext: goJobNext,
  goPrev: goJobPrev,
} = useCursorPage();

const loading = () => loadingTriggers.value || loadingSends.value || loadingJobs.value;

function fmt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

function dayStart(date: string) {
  return new Date(`${date}T00:00:00`).toISOString();
}

function dayEnd(date: string) {
  return new Date(`${date}T23:59:59.999`).toISOString();
}

function baseQuery(): HistoryQuery {
  return {
    since: filters.from ? dayStart(filters.from) : undefined,
    until: filters.to ? dayEnd(filters.to) : undefined,
    camera_id: filters.camera_id || undefined,
    trigger_type: filters.trigger_type || undefined,
    status: filters.status || undefined,
    event_id: filters.event_id.trim() || undefined,
    limit: HISTORY_PAGE_SIZE,
  };
}

async function loadTriggers() {
  loadingTriggers.value = true;
  store.error = "";
  try {
    const data = await api.historyTriggers({
      ...baseQuery(),
      cursor: triggerCursor.value || undefined,
    });
    triggers.value = data.items;
    setTriggerNext(data.next_cursor);
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить историю";
  } finally {
    loadingTriggers.value = false;
  }
}

async function loadSends() {
  loadingSends.value = true;
  store.error = "";
  try {
    const data = await api.historySends({
      ...baseQuery(),
      cursor: sendCursor.value || undefined,
    });
    sends.value = data.items;
    setSendNext(data.next_cursor);
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить историю";
  } finally {
    loadingSends.value = false;
  }
}

async function loadJobs() {
  loadingJobs.value = true;
  try {
    const data = await api.historyOutbound({
      event_id: filters.event_id.trim() || undefined,
      status: filters.job_status || undefined,
      cursor: jobCursor.value || undefined,
      limit: HISTORY_PAGE_SIZE,
    });
    jobs.value = data.items;
    setJobNext(data.next_cursor);
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить очередь";
  } finally {
    loadingJobs.value = false;
  }
}

function loadHistory() {
  resetTriggerPage();
  resetSendPage();
  resetJobPage();
  void Promise.all([loadTriggers(), loadSends(), loadJobs()]);
}

function resetFilters() {
  filters.from = "";
  filters.to = "";
  filters.camera_id = "";
  filters.trigger_type = "";
  filters.status = "";
  filters.job_status = "dead";
  filters.event_id = "";
  loadHistory();
}

function nextTriggers() {
  if (goTriggerNext()) void loadTriggers();
}

function prevTriggers() {
  if (goTriggerPrev()) void loadTriggers();
}

function nextSends() {
  if (goSendNext()) void loadSends();
}

function prevSends() {
  if (goSendPrev()) void loadSends();
}

function nextJobs() {
  if (goJobNext()) void loadJobs();
}

function prevJobs() {
  if (goJobPrev()) void loadJobs();
}

function hasClip(row: TriggerEvent) {
  return Boolean(row.video_url || row.clip?.url || row.clip?.key || row.video_key);
}

function clipSkipReason(row: TriggerEvent) {
  const ev = row.evidence || {};
  const raw = ev.webhook_video_error || ev.clip_error;
  return typeof raw === "string" && raw.trim() ? raw.trim() : "";
}

async function openClip(row: TriggerEvent) {
  playing.value = row;
  playUrl.value = `/api/v1/public/clips/${encodeURIComponent(row.event_id)}.mp4`;
}

function closeClip() {
  playing.value = null;
  playUrl.value = "";
}

async function resend(row: TriggerEvent) {
  busyId.value = row.event_id;
  try {
    const out = await api.resendTrigger(row.event_id);
    flash(out.queued ? `В очередь: ${out.queued}` : "Нечего ставить в очередь");
    await loadJobs();
    await loadSends();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось отправить повторно";
  } finally {
    busyId.value = "";
  }
}

async function retry(job: OutboundJob) {
  busyId.value = job.id;
  try {
    await api.retryOutbound(job.id);
    flash("Повтор поставлен в очередь");
    await loadJobs();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось повторить";
  } finally {
    busyId.value = "";
  }
}

onMounted(() => {
  loadHistory();
});
</script>

<template>
  <div class="stack-lg">
    <form class="card" @submit.prevent="loadHistory">
      <div class="card-head">
        <h2>Фильтры</h2>
        <p class="lede">Запрос уходит на сервер. Пустые поля не учитываются.</p>
      </div>
      <div class="card-body filters-row filters-many">
        <DateRangeField id="hist-range" v-model:from="filters.from" v-model:to="filters.to" label="Период" />
        <div class="ig">
          <label class="form-label" for="hist-camera">Камера</label>
          <div class="form-floating">
            <select id="hist-camera" v-model="filters.camera_id">
              <option value="">Все камеры</option>
              <option v-for="cam in store.cameras" :key="cam.id" :value="cam.id">
                {{ cam.name || cam.id }}
              </option>
            </select>
          </div>
        </div>
        <div class="ig">
          <label class="form-label" for="hist-type">Тип сработки</label>
          <div class="form-floating">
            <select id="hist-type" v-model="filters.trigger_type">
              <option v-for="opt in TRIGGER_TYPES" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>
        <div class="ig">
          <label class="form-label" for="hist-status">Статус отправки</label>
          <div class="form-floating">
            <select id="hist-status" v-model="filters.status">
              <option v-for="opt in STATUSES" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>
        <div class="ig">
          <label class="form-label" for="hist-job">Очередь</label>
          <div class="form-floating">
            <select id="hist-job" v-model="filters.job_status">
              <option v-for="opt in JOB_STATUSES" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>
        <Field id="hist-event" v-model="filters.event_id" label="ID события" />
      </div>
      <div class="card-foot end">
        <div class="row">
          <button type="submit" :disabled="loading()">{{ loading() ? "Загрузка…" : "Применить" }}</button>
          <button type="button" class="ghost" :disabled="loading()" @click="resetFilters">Сбросить</button>
        </div>
      </div>
    </form>

    <section class="card">
      <div class="card-head">
        <h2>Сработки ({{ triggers.length }})</h2>
        <p class="lede">Клип и повторная отправка на все включённые webhook’и.</p>
      </div>
      <div class="card-body">
        <div v-if="triggers.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Камера</th>
                <th>Тип</th>
                <th>Клип</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in triggers" :key="row.event_id + row.created_at">
                <td>{{ fmt(row.created_at) }}</td>
                <td><code>{{ row.camera_name || row.camera_id }}</code></td>
                <td>{{ triggerLabel(row.trigger_type) }}</td>
                <td>
                  <button v-if="hasClip(row)" type="button" class="ghost" @click="openClip(row)">Смотреть</button>
                  <span v-else class="muted" :title="clipSkipReason(row)">{{ clipSkipReason(row) || "нет" }}</span>
                </td>
                <td class="td-action">
                  <button type="button" class="ghost" :disabled="busyId === row.event_id" @click="resend(row)">
                    Повторить
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">{{ loadingTriggers ? "Загрузка…" : "Сработок нет" }}</p>
        </div>
      </div>
      <div v-if="triggerCanPrev || triggerCanNext" class="card-foot end">
        <Pager
          :can-prev="triggerCanPrev"
          :can-next="triggerCanNext"
          :disabled="loadingTriggers"
          @prev="prevTriggers"
          @next="nextTriggers"
        />
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Очередь неудач ({{ jobs.length }})</h2>
        <p class="lede">Исчерпанные и ожидающие доставки. Повтор ставит задачу снова.</p>
      </div>
      <div class="card-body">
        <div v-if="jobs.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Обновлено</th>
                <th>Статус</th>
                <th>Попытки</th>
                <th>URL</th>
                <th>Ошибка</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in jobs" :key="row.id">
                <td>{{ fmt(row.updated_at) }}</td>
                <td>
                  <span class="pill" :class="{ 'pill-ok': row.status === 'ok', 'pill-err': row.status === 'dead' }">
                    {{ row.status }}
                  </span>
                </td>
                <td>{{ row.attempts }}/{{ row.max_attempts }}</td>
                <td class="uri">{{ row.url }}</td>
                <td class="uri">{{ row.last_error || "—" }}</td>
                <td class="td-action">
                  <button
                    v-if="row.status !== 'ok'"
                    type="button"
                    class="ghost"
                    :disabled="busyId === row.id"
                    @click="retry(row)"
                  >
                    Ещё раз
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">{{ loadingJobs ? "Загрузка…" : "Очередь пуста" }}</p>
        </div>
      </div>
      <div v-if="jobCanPrev || jobCanNext" class="card-foot end">
        <Pager
          :can-prev="jobCanPrev"
          :can-next="jobCanNext"
          :disabled="loadingJobs"
          @prev="prevJobs"
          @next="nextJobs"
        />
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Отправки ({{ sends.length }})</h2>
        <p class="lede">Каждая попытка HTTP, включая ретраи.</p>
      </div>
      <div class="card-body">
        <div v-if="sends.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Статус</th>
                <th>HTTP</th>
                <th>URL</th>
                <th>Ошибка</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in sends" :key="row.id || row.event_id + row.created_at">
                <td>{{ fmt(row.created_at) }}</td>
                <td>
                  <span class="pill" :class="{ 'pill-ok': row.status === 'ok', 'pill-err': row.status === 'error' }">
                    {{ row.status }}
                  </span>
                </td>
                <td>{{ row.http_status ?? "—" }}</td>
                <td class="uri">{{ row.url || "—" }}</td>
                <td class="uri">{{ row.error || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">{{ loadingSends ? "Загрузка…" : "Отправок нет" }}</p>
        </div>
      </div>
      <div v-if="sendCanPrev || sendCanNext" class="card-foot end">
        <Pager
          :can-prev="sendCanPrev"
          :can-next="sendCanNext"
          :disabled="loadingSends"
          @prev="prevSends"
          @next="nextSends"
        />
      </div>
    </section>

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
