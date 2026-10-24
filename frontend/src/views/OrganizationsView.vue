<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, api } from "../api";
import { flash, store } from "../store";
import type { Organization } from "../types";

const rows = ref<Organization[]>([]);
const loading = ref(false);
const syncing = ref(false);

async function load() {
  loading.value = true;
  store.error = "";
  try {
    const data = await api.organizations();
    rows.value = data.organizations;
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить организации";
  } finally {
    loading.value = false;
  }
}

async function syncFromBilling() {
  syncing.value = true;
  store.error = "";
  try {
    const result = await api.syncOrganizations();
    if (!result.ok) store.error = result.detail || "Биллинг не ответил";
    else flash(`Обновлено: ${result.synced}`);
    await load();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось забрать организации";
  } finally {
    syncing.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2>Организации ({{ rows.length }})</h2>
        <p class="lede">Название и статус приходят из биллинга. Здесь их нельзя создать.</p>
      </div>
    </div>
    <div class="card-body">
      <div v-if="rows.length" class="table-wrap">
        <table>
          <thead>
            <tr><th>Название</th><th>Описание</th><th>Статус</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td><strong>{{ row.name }}</strong></td>
              <td>{{ row.description || "—" }}</td>
              <td>{{ row.is_active ? "активна" : "выключена" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="lede">{{ loading ? "Загрузка…" : "Организаций нет. Заберите справочник из биллинга." }}</p>
    </div>
    <div class="card-foot end">
      <button type="button" :disabled="syncing" @click="syncFromBilling">
        {{ syncing ? "Обновление…" : "Забрать из биллинга" }}
      </button>
    </div>
  </section>
</template>
