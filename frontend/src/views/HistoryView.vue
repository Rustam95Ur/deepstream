<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import Field from "../components/Field.vue";
import Pager from "../components/Pager.vue";
import { ApiError, api } from "../api";
import { HISTORY_PAGE_SIZE, useCursorPage } from "../cursorPage";
import { store } from "../store";
import type { HistoryQuery, SendEvent, TriggerEvent } from "../types";

const TRIGGER_TYPES = [
  { value: "", label: "Все типы" },
  { value: "presence", label: "Присутствие" },
  { value: "convergence", label: "Схождение" },
  { value: "vif", label: "VIF" },
  { value: "stream_silent", label: "Тишина потока" },
];

const STATUSES = [
  { value: "", label: "Все статусы" },
  { value: "ok", label: "Успех" },
  { value: "error", label: "Ошибка" },
  { value: "skipped", label: "Пропуск" },
];

const filters = reactive({
  from: "",
  to: "",
  camera_id: "",
  trigger_type: "",
  status: "",
  event_id: "",
});

const triggers = ref<TriggerEvent[]>([]);
const sends = ref<SendEvent[]>([]);
const loadingTriggers = ref(false);
const loadingSends = ref(false);
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

const loading = () => loadingTriggers.value || loadingSends.value;

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

function loadHistory() {
  resetTriggerPage();
  resetSendPage();
  void Promise.all([loadTriggers(), loadSends()]);
}

function resetFilters() {
  filters.from = "";
  filters.to = "";
  filters.camera_id = "";
  filters.trigger_type = "";
  filters.status = "";
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
      <div class="card-body form-grid">
        <Field id="hist-from" v-model="filters.from" label="С даты" type="date" />
        <Field id="hist-to" v-model="filters.to" label="До даты" type="date" />
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
        <p class="lede">Последние события детекции на ноде.</p>
      </div>
      <div class="card-body">
        <div v-if="triggers.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Камера</th>
                <th>Тип</th>
                <th>Категория</th>
                <th>Событие</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in triggers" :key="row.event_id + row.created_at">
                <td>{{ fmt(row.created_at) }}</td>
                <td><code>{{ row.camera_id }}</code></td>
                <td>{{ row.trigger_type }}</td>
                <td>{{ row.category }}</td>
                <td class="uri">{{ row.event_id }}</td>
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
        <h2>Отправки ({{ sends.length }})</h2>
        <p class="lede">HTTP POST на URL триггеров.</p>
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
              <tr v-for="row in sends" :key="row.event_id + row.created_at">
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
  </div>
</template>
