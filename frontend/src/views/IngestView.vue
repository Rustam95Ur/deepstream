<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { flash, saveSettings, store } from "../store";
import type { Webhook } from "../types";

const hooks = ref<Webhook[]>([]);
const editingId = ref("");
const showForm = ref(false);
const savingHook = ref(false);

const form = reactive({
  name: "",
  url: "",
  enabled: true,
  hmac_secret: "",
  timeout_sec: 5,
  max_retries: 5,
});

onMounted(() => {
  void loadHooks();
});

async function loadHooks() {
  try {
    hooks.value = (await api.webhooks()).items;
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить webhook’и";
  }
}

function openNew() {
  editingId.value = "";
  form.name = "";
  form.url = "";
  form.enabled = true;
  form.hmac_secret = "";
  form.timeout_sec = 5;
  form.max_retries = 5;
  showForm.value = true;
}

function openEdit(hook: Webhook) {
  editingId.value = hook.id;
  form.name = hook.name;
  form.url = hook.url;
  form.enabled = hook.enabled;
  form.hmac_secret = "";
  form.timeout_sec = hook.timeout_sec;
  form.max_retries = hook.max_retries;
  showForm.value = true;
}

function closeForm() {
  showForm.value = false;
}

async function saveHook() {
  const url = form.url.trim();
  if (!url) return;
  savingHook.value = true;
  try {
    const body = {
      name: form.name.trim() || "webhook",
      url,
      enabled: form.enabled,
      timeout_sec: Number(form.timeout_sec) || 5,
      max_retries: Number(form.max_retries) || 0,
      hmac_secret: form.hmac_secret.trim() ? form.hmac_secret.trim() : editingId.value ? null : "",
    };
    if (editingId.value) {
      await api.updateWebhook(editingId.value, body);
      flash("Webhook обновлён");
    } else {
      await api.createWebhook(body);
      flash("Webhook добавлен");
    }
    showForm.value = false;
    await loadHooks();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось сохранить webhook";
  } finally {
    savingHook.value = false;
  }
}

async function removeHook(hook: Webhook) {
  if (!confirm(`Удалить «${hook.name}»?`)) return;
  try {
    await api.deleteWebhook(hook.id);
    flash("Webhook удалён");
    await loadHooks();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось удалить webhook";
  }
}
</script>

<template>
  <div v-if="store.settings" class="stack-lg">
    <form class="card" @submit.prevent="saveSettings">
      <div class="card-head">
        <h2>Интеграции</h2>
        <p class="lede">Список камер, клипы и глобальный выключатель HTTP.</p>
      </div>
      <div class="card-body form-grid">
        <Field id="cameras-url" v-model="store.settings.cameras_url" class="span-2" label="URL списка камер" addon="GET" />
        <Field id="poll-sec" v-model="store.settings.cameras_poll_sec" label="Интервал опроса, сек" type="number" />
        <div><SwitchField id="http-sink" v-model="store.settings.enable_http_sink" label="Отправка по HTTP" /></div>
        <div><SwitchField id="clip-record" v-model="store.settings.enable_clip_record" label="Ring-buffer клипов" /></div>
      </div>
      <div class="card-foot end">
        <button type="submit" :disabled="store.saving">Сохранить</button>
      </div>
    </form>

    <section class="card">
      <div class="card-head">
        <h2>Webhook’и ({{ hooks.length }})</h2>
        <p class="lede">Каждый включённый URL получает тот же контракт. HMAC необязателен.</p>
      </div>
      <div class="card-body">
        <div v-if="hooks.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>URL</th>
                <th>HMAC</th>
                <th>Ретраи</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="hook in hooks" :key="hook.id">
                <td>
                  {{ hook.name }}
                  <span class="pill" :class="hook.enabled ? 'pill-ok' : 'pill-err'">
                    {{ hook.enabled ? "вкл" : "выкл" }}
                  </span>
                </td>
                <td class="uri">{{ hook.url }}</td>
                <td>{{ hook.hmac_configured ? "да" : "нет" }}</td>
                <td>{{ hook.max_retries }}</td>
                <td class="td-action">
                  <div class="row">
                    <button type="button" class="ghost" @click="openEdit(hook)">Изменить</button>
                    <button type="button" class="ghost" @click="removeHook(hook)">Удалить</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Webhook’ов нет</p>
          <p class="lede">События останутся в истории, но наружу не уйдут.</p>
        </div>
      </div>
      <div class="card-foot end">
        <button type="button" @click="openNew">Добавить</button>
      </div>
    </section>

    <div v-if="showForm" class="modal-scrim" @click.self="closeForm">
      <form class="card modal modal-form" @submit.prevent="saveHook">
        <div class="card-head">
          <h2>{{ editingId ? "Изменить webhook" : "Новый webhook" }}</h2>
          <p class="lede">Подпись: HMAC-SHA256(secret, timestamp + "." + body).</p>
        </div>
        <div class="card-body form-grid">
          <Field id="wh-name" v-model="form.name" label="Имя" />
          <Field id="wh-url" v-model="form.url" class="span-2" label="URL" addon="POST" required />
          <Field
            id="wh-secret"
            v-model="form.hmac_secret"
            class="span-2"
            :label="editingId ? 'HMAC-секрет (пусто = не менять)' : 'HMAC-секрет'"
          />
          <Field id="wh-timeout" v-model="form.timeout_sec" label="Таймаут, сек" type="number" />
          <Field id="wh-retries" v-model="form.max_retries" label="Повторы после ошибки" type="number" />
          <div class="span-2">
            <SwitchField id="wh-enabled" v-model="form.enabled" label="Включён" />
          </div>
        </div>
        <div class="card-foot end">
          <div class="row">
            <button type="submit" :disabled="savingHook">{{ savingHook ? "Сохранение…" : "Сохранить" }}</button>
            <button type="button" class="ghost" @click="closeForm">Отмена</button>
          </div>
        </div>
      </form>
    </div>
  </div>
</template>
