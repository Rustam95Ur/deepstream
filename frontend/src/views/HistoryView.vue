<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, api } from "../api";
import { store } from "../store";
import type { SendEvent, TriggerEvent } from "../types";

const triggers = ref<TriggerEvent[]>([]);
const sends = ref<SendEvent[]>([]);

function fmt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

onMounted(async () => {
  try {
    const [t, s] = await Promise.all([api.historyTriggers(), api.historySends()]);
    triggers.value = t;
    sends.value = s;
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить историю";
  }
});
</script>

<template>
  <div class="stack-lg">
    <section class="card">
      <div class="card-head">
        <h2>Сработки ({{ triggers.length }})</h2>
        <p class="lede">Последние события детекции на ноде.</p>
      </div>
      <div class="card-body">
        <div v-if="triggers.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Камера</th>
                <th>Тип</th>
                <th>Категория</th>
                <th>Событие</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in triggers" :key="row.event_id + row.created_at">
                <td>{{ fmt(row.created_at) }}</td>
                <td><code>{{ row.camera_id }}</code></td>
                <td>{{ row.trigger_type }}</td>
                <td>{{ row.category }}</td>
                <td class="uri">{{ row.event_id }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Сработок пока нет</p>
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Отправки ({{ sends.length }})</h2>
        <p class="lede">HTTP POST на URL триггеров.</p>
      </div>
      <div class="card-body">
        <div v-if="sends.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Статус</th>
                <th>HTTP</th>
                <th>URL</th>
                <th>Ошибка</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in sends" :key="row.event_id + row.created_at">
                <td>{{ fmt(row.created_at) }}</td>
                <td>
                  <span class="pill" :class="{ 'pill-ok': row.status === 'ok', 'pill-err': row.status === 'error' }">
                    {{ row.status }}
                  </span>
                </td>
                <td>{{ row.http_status ?? "—" }}</td>
                <td class="uri">{{ row.url || "—" }}</td>
                <td class="uri">{{ row.error || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Отправок пока нет</p>
        </div>
      </div>
    </section>
  </div>
</template>
