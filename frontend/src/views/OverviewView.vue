<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { enabledCount, store } from "../store";
import type { VideoHealth } from "../types";

const health = ref<VideoHealth | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

async function loadHealth() {
  try {
    health.value = await api.videoHealth();
  } catch {
    health.value = null;
  }
}

function ringLabel(cam: VideoHealth["cameras"][number]) {
  if (!cam.alive) return "упал";
  if (cam.stalled) return "застой";
  return "живой";
}

onMounted(() => {
  void loadHealth();
  timer = setInterval(() => {
    void loadHealth();
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
          <span v-if="store.worker.last_error && store.worker.last_error !== store.worker.detail" class="field-error">
            {{ store.worker.last_error }}
          </span>
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
          <span>включено на этой ноде</span>
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
          <span>{{ health?.clip_record ? "клипы включены" : "клипы выкл" }}</span>
        </div>
      </article>
    </div>

    <section v-if="health?.cameras.length" class="card">
      <div class="card-head">
        <h2>Здоровье видеоконтура</h2>
        <p class="lede">RTSP ring-buffer по каждой камере: процесс, сегменты, рестарты.</p>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Камера</th>
                <th>Статус</th>
                <th>Кодек</th>
                <th>Сегмент</th>
                <th>Рестарты</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="cam in health.cameras" :key="cam.camera_id">
                <td>{{ cam.name || cam.camera_id }}</td>
                <td>
                  <span
                    class="pill"
                    :class="{
                      'pill-ok': cam.alive && !cam.stalled,
                      'pill-err': !cam.alive || cam.stalled,
                    }"
                  >
                    {{ ringLabel(cam) }}
                  </span>
                </td>
                <td>{{ cam.codec || "—" }}</td>
                <td>{{ cam.last_segment_age_s == null ? "нет" : `${cam.last_segment_age_s} с` }}</td>
                <td>{{ cam.restarts }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>
