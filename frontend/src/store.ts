import { computed, reactive } from "vue";
import { ApiError, api } from "./api";
import type { Camera, NodeSettings, Session, WorkerStatus } from "./types";

export const store = reactive({
  loaded: false,
  settings: null as NodeSettings | null,
  session: null as Session | null,
  cameras: [] as Camera[],
  worker: null as WorkerStatus | null,
  workerBusy: false,
  message: "",
  error: "",
  saving: false,
});

export const enabledCount = computed(
  () => store.cameras.filter((c) => c.enabled).length,
);

let flashTimer: ReturnType<typeof setTimeout> | null = null;
const FLASH_MS = 3500;

export function flash(text: string) {
  store.message = text;
  store.error = "";
  if (flashTimer) clearTimeout(flashTimer);
  flashTimer = setTimeout(() => {
    if (store.message === text) store.message = "";
    flashTimer = null;
  }, FLASH_MS);
}

export async function loadConsole() {
  store.error = "";
  try {
    const [s, c, w, sess] = await Promise.all([
      api.settings(),
      api.cameras(),
      api.worker(),
      api.session(),
    ]);
    store.settings = s;
    store.cameras = c.cameras;
    store.worker = w;
    store.session = sess;
    store.loaded = true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) throw err;
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить данные";
  }
}

export async function saveSettings() {
  if (!store.settings) return;
  store.saving = true;
  try {
    store.settings = await api.saveSettings(store.settings);
    flash("Сохранено");
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось сохранить";
  } finally {
    store.saving = false;
  }
}

export async function refreshCameras() {
  store.cameras = (await api.cameras()).cameras;
}

async function refreshWorker() {
  store.worker = await api.worker();
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function startWorker() {
  store.workerBusy = true;
  try {
    store.worker = await api.workerStart();
    await wait(400);
    await refreshWorker();
    flash(store.worker?.running ? "Pipeline запущен" : "Pipeline не запустился");
  } finally {
    store.workerBusy = false;
  }
}

export async function stopWorker() {
  store.workerBusy = true;
  try {
    store.worker = await api.workerStop();
    await wait(300);
    await refreshWorker();
    flash(store.worker?.running ? "Остановка не завершилась" : "Pipeline остановлен");
  } finally {
    store.workerBusy = false;
  }
}
