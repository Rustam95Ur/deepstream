<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, api } from "../api";
import { flash, store } from "../store";
import type { Organization } from "../types";

const rows = ref<Organization[]>([]);
const loading = ref(false);
const syncing = ref(false);
const saving = ref(false);
const name = ref("");
const description = ref("");
const cloud = computed(() => Boolean(store.session?.sso));

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

async function createLocal() {
  const next = name.value.trim();
  if (!next || saving.value) return;
  saving.value = true;
  store.error = "";
  try {
    await api.createOrganization({ name: next, description: description.value.trim() });
    name.value = "";
    description.value = "";
    flash("Организация создана");
    await load();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось создать организацию";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2>Организации ({{ rows.length }})</h2>
        <p class="lede">
          {{
            cloud
              ? "Название и статус приходят из биллинга. Здесь их нельзя создать."
              : "Организации хранятся в локальной базе. Справочник биллинга не используется."
          }}
        </p>
      </div>
    </div>
    <div class="card-body">
      <form v-if="!cloud" class="row" @submit.prevent="createLocal">
        <input v-model="name" placeholder="Название" required />
        <input v-model="description" placeholder="Описание" />
        <button type="submit" :disabled="saving">{{ saving ? "Сохранение…" : "Добавить" }}</button>
      </form>
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
      <p v-else class="lede">
        {{
          loading
            ? "Загрузка…"
            : cloud
              ? "Организаций нет. Заберите справочник из биллинга."
              : "Организаций пока нет."
        }}
      </p>
    </div>
    <div v-if="cloud" class="card-foot end">
      <button type="button" :disabled="syncing" @click="syncFromBilling">
        {{ syncing ? "Обновление…" : "Забрать из биллинга" }}
      </button>
    </div>
  </section>
</template>
