<script setup lang="ts">
import { computed, ref } from "vue";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { flash, refreshCameras, store } from "../store";
import type { Camera } from "../types";

const camId = ref("");
const camName = ref("");
const camUri = ref("");
const camEnabled = ref(true);
const pendingDelete = ref<Camera | null>(null);

const filtered = computed(() => {
  const q = store.search.trim().toLowerCase();
  if (!q) return store.cameras;
  return store.cameras.filter(
    (c) =>
      c.id.toLowerCase().includes(q) ||
      c.name.toLowerCase().includes(q) ||
      c.main_uri.toLowerCase().includes(q),
  );
});

async function addCamera() {
  const uri = camUri.value.trim();
  if (!uri) return;
  try {
    const id = camId.value.trim() || `cam_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
    await api.upsertCamera({
      id,
      name: camName.value.trim() || id,
      main_uri: uri,
      enabled: camEnabled.value,
    });
    camId.value = "";
    camName.value = "";
    camUri.value = "";
    camEnabled.value = true;
    await refreshCameras();
    flash("Камера сохранена");
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось сохранить камеру";
  }
}

async function confirmDelete() {
  const cam = pendingDelete.value;
  if (!cam) return;
  try {
    await api.deleteCamera(cam.id);
    store.cameras = store.cameras.filter((c) => c.id !== cam.id);
    pendingDelete.value = null;
    flash("Камера удалена");
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось удалить";
  }
}
</script>

<template>
  <div class="stack-lg">
    <section class="card">
      <div class="card-head">
        <h2>Добавить камеру</h2>
        <p class="lede">Пустой id выдаётся автоматически.</p>
      </div>
      <form class="card-body form-grid" @submit.prevent="addCamera">
        <Field id="cam-id" v-model="camId" label="id" addon="ID" />
        <Field id="cam-name" v-model="camName" label="name" addon="Name" />
        <Field id="cam-uri" v-model="camUri" class="span-2" label="RTSP / URI" addon="rtsp://" required />
        <div class="span-2">
          <SwitchField id="cam-enabled" v-model="camEnabled" label="enabled" />
        </div>
        <div class="form-actions span-2">
          <button type="submit">Добавить</button>
        </div>
      </form>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Реестр ({{ filtered.length }})</h2>
        <p class="lede">Удаление снимает поток с ноды.</p>
      </div>
      <div class="card-body">
        <div v-if="filtered.length" class="table-wrap">
          <table>
            <thead>
              <tr><th>id</th><th>name</th><th>uri</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="c in filtered" :key="c.id">
                <td>
                  <code>{{ c.id }}</code>
                  <span v-if="!c.enabled" class="pill">off</span>
                </td>
                <td>{{ c.name }}</td>
                <td class="uri">{{ c.main_uri }}</td>
                <td class="td-action">
                  <button type="button" class="ghost danger" :aria-label="`Удалить камеру ${c.id}`" @click="pendingDelete = c">Удалить</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Камер пока нет</p>
          <p class="lede">Добавьте поток в форме выше или через API.</p>
        </div>
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
