<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { flash, refreshCameras, store } from "../store";
import type { Camera } from "../types";

const router = useRouter();
const pendingDelete = ref<Camera | null>(null);
const toggling = ref("");

async function toggleEnabled(cam: Camera, enabled: boolean) {
  if (toggling.value) return;
  toggling.value = cam.id;
  const prev = cam.enabled;
  cam.enabled = enabled;
  try {
    await api.updateCamera(cam.id, { ...cam, enabled });
    await refreshCameras();
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
        <h2>Реестр ({{ store.cameras.length }})</h2>
        <p class="lede">Статус применяется сразу. Изменение и удаление влияют на поток.</p>
      </div>
      <div class="card-body">
        <div v-if="store.cameras.length" class="table-wrap">
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
              <tr v-for="c in store.cameras" :key="c.id">
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
          <p class="empty-title">Камер пока нет</p>
          <p class="lede">Добавьте поток кнопкой выше или через API.</p>
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
