<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ApiError, api } from "../api";
import { store } from "../store";
import { triggerLabel } from "../schoolAlgorithms";
import type { LabCatalog, LabResult, LabScenario, LabVideo } from "../types";

const catalog = ref<LabCatalog | null>(null);
const busy = ref("");
const preview = ref<{ title: string; url: string } | null>(null);

const running = computed(() => catalog.value?.run.status === "running");
const videoCount = computed(() =>
  (catalog.value?.scenarios || []).reduce((sum, item) => sum + item.videos.length, 0),
);

const VERDICT: Record<string, string> = {
  hit: "Совпало",
  miss: "Другой сценарий",
  no_model: "Модели нет",
  file_skip: "На файле не проверяется",
  error: "Ошибка",
  cancelled: "Остановлен",
};

let timer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  void load();
  timer = setInterval(() => {
    if (running.value) void load(true);
  }, 2000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

async function load(quiet = false) {
  try {
    catalog.value = await api.scenarioLab();
  } catch (err) {
    if (!quiet) {
      store.error = err instanceof ApiError ? err.message : "Не удалось открыть историю роликов";
    }
  }
}

function resultOf(scenario: string, eventId: string): LabResult | null {
  const rows = catalog.value?.run.results || [];
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (row.scenario === scenario && row.event_id === eventId) return row;
  }
  return null;
}

function watching(video: LabVideo) {
  const run = catalog.value?.run;
  return run?.status === "running" && run.current_event === video.event_id;
}

function verdictText(video: LabVideo) {
  if (watching(video)) return "Смотрит";
  const row = resultOf(video.scenario, video.event_id);
  if (!row) return "";
  return VERDICT[row.verdict] || row.verdict;
}

function verdictClass(video: LabVideo) {
  if (watching(video)) return "badge-primary";
  const row = resultOf(video.scenario, video.event_id);
  if (!row) return "badge-muted";
  if (row.verdict === "hit") return "badge-ok";
  if (row.verdict === "miss" || row.verdict === "error") return "badge-warn";
  return "badge-muted";
}

function detectedText(video: LabVideo) {
  const row = resultOf(video.scenario, video.event_id);
  if (!row || !row.detected.length) return "";
  return row.detected.map((item) => triggerLabel(item)).join(", ");
}

function formatSize(size: number) {
  if (!size) return "";
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function formatWhen(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ru-RU");
}

async function run(scenario = "") {
  if (busy.value || running.value) return;
  busy.value = scenario ? `run:${scenario}` : "all";
  store.error = "";
  try {
    catalog.value = await api.runScenarioLab(scenario);
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось запустить прогон";
  } finally {
    busy.value = "";
  }
}

async function cancel() {
  if (busy.value) return;
  busy.value = "cancel";
  store.error = "";
  try {
    catalog.value = await api.cancelScenarioLab();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось остановить прогон";
  } finally {
    busy.value = "";
  }
}

function openPreview(scenario: LabScenario, video: LabVideo) {
  preview.value = {
    title: `${scenario.label} · ${video.camera_name || video.event_id}`,
    url: api.scenarioClipUrl(video.event_id),
  };
}

function closePreview() {
  preview.value = null;
}
</script>

<template>
  <div v-if="catalog" class="stack-lg">
    <section class="card">
      <div class="card-head">
        <h2>Ролики из истории</h2>
        <p class="lede">
          Берутся последние события, у которых ролик ещё лежит в MinIO.
          Прогон скачивает файл и смотрит его тем же детектором, что и камеру.
          Рядом с исходным сценарием видно, что сработало сейчас. В Campus ничего не уходит.
        </p>
      </div>
      <div class="card-body">
        <p v-if="running" class="lede">
          Сейчас {{ catalog.run.current_file || "запуск" }}
          <template v-if="catalog.run.paused_live"> · живые камеры на паузе и вернутся после прогона</template>
        </p>
        <p v-else-if="catalog.run.error" class="lede">{{ catalog.run.error }}</p>
        <p class="lab-path">{{ catalog.root }}</p>
        <div class="row lab-actions">
          <button type="button" :disabled="!!busy || running || !videoCount" @click="run()">
            {{ busy === "all" ? "Запуск…" : "Прогнать все" }}
          </button>
          <button v-if="running" type="button" class="ghost" :disabled="busy === 'cancel'" @click="cancel">
            {{ busy === "cancel" ? "Остановка…" : "Остановить прогон" }}
          </button>
        </div>
      </div>
    </section>

    <div class="lab-grid">
      <section v-for="scenario in catalog.scenarios" :key="scenario.id" class="card">
        <div class="card-head">
          <h2>
            {{ scenario.label }}
            <span v-if="!scenario.ready" class="pill">скоро</span>
          </h2>
          <p class="lede">{{ scenario.hint }}</p>
        </div>
        <div class="card-body">
          <button
            type="button"
            class="ghost"
            :disabled="!!busy || running || !scenario.videos.length"
            @click="run(scenario.id)"
          >
            {{ busy === `run:${scenario.id}` ? "Запуск…" : "Прогнать" }}
          </button>
          <p v-if="!scenario.videos.length" class="lede lab-actions">В истории нет ролика.</p>
          <ul v-else class="lab-files">
            <li v-for="video in scenario.videos" :key="video.event_id" class="lab-file">
              <button type="button" class="ghost" @click="openPreview(scenario, video)">
                {{ video.camera_name || video.event_id }}
              </button>
              <span class="muted">{{ formatWhen(video.created_at) }}</span>
              <span v-if="formatSize(video.size)" class="muted">{{ formatSize(video.size) }}</span>
              <span v-if="verdictText(video)" class="badge" :class="verdictClass(video)">
                {{ verdictText(video) }}
              </span>
              <span v-if="detectedText(video)" class="muted">Сейчас: {{ detectedText(video) }}</span>
              <span v-if="resultOf(scenario.id, video.event_id)?.error" class="muted">
                {{ resultOf(scenario.id, video.event_id)?.error }}
              </span>
            </li>
          </ul>
        </div>
      </section>
    </div>

    <div v-if="preview" class="modal-scrim" @click.self="closePreview">
      <section class="card modal modal-video">
        <div class="card-head">
          <h2>{{ preview.title }}</h2>
        </div>
        <div class="card-body">
          <video class="clip-player" :src="preview.url" controls autoplay />
        </div>
        <div class="card-foot end">
          <button type="button" class="ghost" @click="closePreview">Закрыть</button>
        </div>
      </section>
    </div>
  </div>
</template>
