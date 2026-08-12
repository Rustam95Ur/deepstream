<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, api } from "../api";
import Logo from "../components/Logo.vue";
import { enabledCount, loadConsole, startWorker, stopWorker, store } from "../store";

const route = useRoute();
const router = useRouter();
const mobileOpen = ref(false);
const userOpen = ref(false);

const titles: Record<string, { title: string; desc: string }> = {
  overview: { title: "Обзор", desc: "Статус pipeline и ноды" },
  cameras: { title: "Камеры", desc: "Потоки на этой ноде" },
  node: { title: "Нода", desc: "Идентификация и лимиты" },
  ingest: { title: "Связь", desc: "Campus, HTTP и Celery" },
  triggers: { title: "Триггеры", desc: "Пороги детекции" },
};

const page = computed(() => titles[String(route.name)] || titles.overview);
const pipelinePct = computed(() => (store.worker?.running ? 100 : 0));

const nav = [
  { name: "overview", label: "Обзор", icon: "home" },
  { name: "cameras", label: "Камеры", icon: "cam" },
  { name: "node", label: "Нода", icon: "node" },
  { name: "ingest", label: "Связь", icon: "link" },
  { name: "triggers", label: "Триггеры", icon: "bolt" },
] as const;

onMounted(async () => {
  document.addEventListener("click", onDocClick);
  try {
    await loadConsole();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await router.push({ name: "login" });
    }
  }
});

onUnmounted(() => {
  document.removeEventListener("click", onDocClick);
});

function onDocClick() {
  userOpen.value = false;
}

async function logout() {
  await api.logout();
  await router.push({ name: "login" });
}

function go(name: string) {
  mobileOpen.value = false;
  router.push({ name });
}

async function onStart() {
  try {
    await startWorker();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось запустить";
  }
}

async function onStop() {
  try {
    await stopWorker();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось остановить";
  }
}
</script>

<template>
  <div class="app" :class="{ 'mobile-open': mobileOpen }">
    <header class="app-header">
      <div class="app-header-inner">
        <div class="app-header-logo">
          <button type="button" class="btn-mobile" aria-label="Меню" @click.stop="mobileOpen = !mobileOpen">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
              <path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
            </svg>
          </button>
          <button type="button" class="logo-btn" aria-label="Nexus" @click="go('overview')">
            <Logo :height="32" />
            <span>Nexus</span>
          </button>
        </div>
        <div class="app-navbar">
          <label class="header-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="6.5" stroke="currentColor" stroke-width="1.7"/>
              <path d="M16 16.5 20 20.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
            </svg>
            <input v-model="store.search" type="search" placeholder="Поиск" />
          </label>
          <div class="user-wrap" @click.stop>
            <button type="button" class="user-btn" @click="userOpen = !userOpen">
              <span class="user-meta">
                <strong>{{ store.settings?.node_name || "Node" }}</strong>
                <small>{{ store.settings?.node_id }}</small>
              </span>
              <span class="avatar">{{ (store.settings?.node_name || "N").slice(0, 1) }}</span>
            </button>
            <div v-if="userOpen" class="dropdown">
              <button type="button" class="dropdown-item" @click="logout">Выйти</button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <aside class="app-sidebar" aria-label="Сервисы">
      <div class="sidebar-progress">
        <div class="sidebar-progress-head">
          <span>Pipeline</span>
          <span class="text-primary">{{ store.worker?.running ? "running" : "idle" }}</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: pipelinePct + '%' }"></div>
        </div>
        <p class="sidebar-progress-note">
          {{ store.worker?.detail || "нет статуса" }}
        </p>
      </div>

      <div class="sidebar-stats">
        <div class="dash-stat">
          <span>Камеры</span>
          <strong>{{ enabledCount }}</strong>
        </div>
        <div class="dash-stat">
          <span>Лимит</span>
          <strong>{{ store.settings?.max_streams ?? "—" }}</strong>
        </div>
      </div>

      <h3 class="sidebar-title">Сервисы</h3>
      <nav class="service-grid">
        <button
          v-for="item in nav"
          :key="item.name"
          type="button"
          class="service-tile"
          :class="{ active: route.name === item.name }"
          @click="go(item.name)"
        >
          <span class="tile-icon" aria-hidden="true">
            <svg v-if="item.icon === 'home'" width="26" height="26" viewBox="0 0 24 24" fill="none">
              <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
            <svg v-else-if="item.icon === 'cam'" width="26" height="26" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="7" width="13" height="11" rx="2" stroke="currentColor" stroke-width="1.6"/>
              <path d="M16 11.5 21 9v8l-5-2.5v-3Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
            <svg v-else-if="item.icon === 'node'" width="26" height="26" viewBox="0 0 24 24" fill="none">
              <rect x="4" y="4" width="16" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/>
              <path d="M8 12h8M12 8v8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
            </svg>
            <svg v-else-if="item.icon === 'link'" width="26" height="26" viewBox="0 0 24 24" fill="none">
              <path d="M10 13a5 5 0 0 0 7.07 0l1.41-1.41a5 5 0 0 0-7.07-7.07L10 5.93" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
              <path d="M14 11a5 5 0 0 0-7.07 0L5.52 12.4a5 5 0 0 0 7.07 7.07L14 18.07" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
            </svg>
            <svg v-else width="26" height="26" viewBox="0 0 24 24" fill="none">
              <path d="M13 3 5 14h7l-1 7 8-11h-7l1-7Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
          </span>
          <span>{{ item.label }}</span>
        </button>
      </nav>
    </aside>

    <div class="app-main">
      <div class="app-toolbar">
        <div class="page-title">
          <h1>
            <span class="fw-light">{{ route.name === 'overview' ? 'Welcome back,' : '' }}</span>
            {{ route.name === 'overview' ? (store.settings?.node_name || 'Node') : page.title }}
          </h1>
          <p class="page-desc">
            {{ route.name === 'overview' ? 'Вы вошли как оператор этой ноды' : page.desc }}
          </p>
        </div>
        <div v-if="route.name === 'overview'" class="toolbar-actions">
          <button type="button" class="btn-success" @click="onStart">Start</button>
          <button type="button" class="btn-dark" @click="onStop">Stop</button>
        </div>
      </div>

      <main class="app-content">
        <p v-if="store.message" class="alert" role="status">{{ store.message }}</p>
        <p v-if="store.error" class="alert err-banner" role="alert">{{ store.error }}</p>
        <router-view v-if="store.loaded" />
        <div v-else class="stats">
          <div class="card skeleton"></div>
          <div class="card skeleton"></div>
          <div class="card skeleton"></div>
        </div>
      </main>
    </div>
    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false"></div>
  </div>
</template>
