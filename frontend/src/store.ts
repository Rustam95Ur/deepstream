import { computed, reactive } from "vue";
import { ApiError, api } from "./api";
import type { Camera, NodeSettings, WorkerStatus } from "./types";

export const store = reactive({
  loaded: false,
  settings: null as NodeSettings | null,
  cameras: [] as Camera[],
  worker: null as WorkerStatus | null,
  message: "",
  error: "",
  saving: false,
  search: "",
});

export const enabledCount = computed(
  () => store.cameras.filter((c) => c.enabled).length,
);

export function flash(text: string) {
  store.message = text;
  store.error = "";
}

export async function loadConsole() {
  store.error = "";
  try {
    const [s, c, w] = await Promise.all([api.settings(), api.cameras(), api.worker()]);
    store.settings = s;
    store.cameras = c.cameras;
    store.worker = w;
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

export async function startWorker() {
  store.worker = await api.workerStart();
  flash("Pipeline запущен");
}

export async function stopWorker() {
  store.worker = await api.workerStop();
  flash("Pipeline остановлен");
}
