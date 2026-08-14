<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import DateRangeField from "../components/DateRangeField.vue";
import Field from "../components/Field.vue";
import Pager from "../components/Pager.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { PAGE_SIZE, useCursorPage } from "../cursorPage";
import { flash, refreshCameras, store } from "../store";
import type { Camera, CameraQuery } from "../types";

const ENABLED_OPTS = [
  { value: "", label: "Все" },
  { value: "true", label: "Включены" },
  { value: "false", label: "Выключены" },
];

const router = useRouter();
const pendingDelete = ref<Camera | null>(null);
const toggling = ref("");
const loading = ref(false);
const rows = ref<Camera[]>([]);
const { cursor, canPrev, canNext, resetPage, setNext, goNext, goPrev } = useCursorPage();
const filters = reactive({
  q: "",
  enabled: "",
  from: "",
  to: "",
});

function dayStart(date: string) {
  return new Date(`${date}T00:00:00`).toISOString();
}

function dayEnd(date: string) {
  return new Date(`${date}T23:59:59.999`).toISOString();
}

function query(): CameraQuery {
  return {
    q: filters.q.trim() || undefined,
    enabled: filters.enabled === "" ? undefined : filters.enabled === "true",
    since: filters.from ? dayStart(filters.from) : undefined,
    until: filters.to ? dayEnd(filters.to) : undefined,
    cursor: cursor.value || undefined,
    limit: PAGE_SIZE,
  };
}

async function loadCameras() {
  loading.value = true;
  store.error = "";
  try {
    const data = await api.cameras(query());
    rows.value = data.cameras;
    setNext(data.next_cursor);
    if (!rows.value.length && goPrev()) {
      await loadCameras();
    }
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить камеры";
  } finally {
    loading.value = false;
  }
}

function applyFilters() {
  resetPage();
  void loadCameras();
}

function resetFilters() {
  filters.q = "";
  filters.enabled = "";
  filters.from = "";
  filters.to = "";
  applyFilters();
}

function nextPage() {
  if (goNext()) void loadCameras();
}

function prevPage() {
  if (goPrev()) void loadCameras();
}

async function toggleEnabled(cam: Camera, enabled: boolean) {
  if (toggling.value) return;
  toggling.value = cam.id;
  const prev = cam.enabled;
  cam.enabled = enabled;
  try {
    await api.updateCamera(cam.id, { ...cam, enabled });
    await Promise.all([refreshCameras(), loadCameras()]);
  } catch (err) {
    cam.enabled = prev;
    store.error = err instanceof ApiError ? err.message : "Не удалось сменить статус";
  } finally {
    toggling.value = "";
  }
}

async function confirmDelete() {
  const cam = pendingDelete.value;
  if (!cam) return;
  try {
    await api.deleteCamera(cam.id);
    pendingDelete.value = null;
    flash("Камера удалена");
    await Promise.all([refreshCameras(), loadCameras()]);
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось удалить";
  }
}

onMounted(() => {
  void loadCameras();
});
</script>

<template>
  <div class="stack-lg">
    <form class="card" @submit.prevent="applyFilters">
      <div class="card-head">
        <h2>Фильтры</h2>
        <p class="lede">Запрос уходит на сервер. Пустые поля не учитываются.</p>
      </div>
      <div class="card-body filters-row">
        <Field id="cam-q" v-model="filters.q" label="Поиск" />
        <div class="ig">
          <label class="form-label" for="cam-enabled">Статус</label>
          <div class="form-floating">
            <select id="cam-enabled" v-model="filters.enabled">
              <option v-for="opt in ENABLED_OPTS" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>
        <DateRangeField id="cam-range" v-model:from="filters.from" v-model:to="filters.to" label="Период" />
      </div>
      <div class="card-foot end">
        <div class="row">
          <button type="submit" :disabled="loading">{{ loading ? "Загрузка…" : "Применить" }}</button>
          <button type="button" class="ghost" :disabled="loading" @click="resetFilters">Сбросить</button>
        </div>
      </div>
    </form>

    <section class="card">
      <div class="card-head">
        <h2>Реестр ({{ rows.length }})</h2>
        <p class="lede">Статус применяется сразу. Изменение и удаление влияют на поток.</p>
      </div>
      <div class="card-body">
        <div v-if="rows.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Статус</th>
                <th>ID</th>
                <th>Имя</th>
                <th>Адрес</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in rows" :key="c.id">
                <td class="td-status">
                  <SwitchField
                    :id="`cam-on-${c.id}`"
                    :model-value="c.enabled"
                    label="Включена"
                    compact
                    :disabled="toggling === c.id"
                    @update:model-value="(v) => toggleEnabled(c, v)"
                  />
                </td>
                <td><code>{{ c.id }}</code></td>
                <td>{{ c.name }}</td>
                <td class="uri">{{ c.main_uri }}</td>
                <td class="td-action">
                  <div class="row">
                    <button
                      type="button"
                      class="ghost"
                      :aria-label="`Изменить камеру ${c.id}`"
                      @click="router.push({ name: 'camera-edit', params: { id: c.id } })"
                    >Изменить</button>
                    <button
                      type="button"
                      class="ghost danger"
                      :aria-label="`Удалить камеру ${c.id}`"
                      @click="pendingDelete = c"
                    >Удалить</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">{{ loading ? "Загрузка…" : "Камер не найдено" }}</p>
          <p class="lede">Измените фильтры или добавьте поток кнопкой выше.</p>
        </div>
      </div>
      <div v-if="canPrev || canNext" class="card-foot end">
        <Pager
          :can-prev="canPrev"
          :can-next="canNext"
          :disabled="loading"
          @prev="prevPage"
          @next="nextPage"
        />
      </div>
    </section>

    <div v-if="pendingDelete" class="modal-scrim" @click.self="pendingDelete = null">
      <div class="card modal" role="dialog" aria-modal="true" aria-labelledby="del-title">
        <div class="card-head">
          <h2 id="del-title">Удалить камеру?</h2>
        </div>
        <div class="card-body">
          <p class="lede"><code>{{ pendingDelete.id }}</code> будет снята с ноды.</p>
          <div class="row modal-actions">
            <button type="button" class="danger-fill" @click="confirmDelete">Удалить</button>
            <button type="button" class="ghost" @click="pendingDelete = null">Отмена</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
