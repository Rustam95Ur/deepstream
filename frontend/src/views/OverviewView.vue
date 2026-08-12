<script setup lang="ts">
import { enabledCount, store } from "../store";
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
          <span v-if="store.worker.last_error && store.worker.last_error !== store.worker.detail" class="muted">
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
          <h2>Автозапуск</h2>
        </div>
        <div class="stat-body">
          <span class="stat-icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.8"/>
              <path d="M12 8v4l3 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
          </span>
          <p class="stat-v">{{ store.settings.auto_start_pipeline ? "вкл" : "выкл" }}</p>
        </div>
        <div class="card-foot">
          <span>при старте процесса</span>
        </div>
      </article>
    </div>
  </div>
</template>
