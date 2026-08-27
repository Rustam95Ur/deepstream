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
  login: "",
  password: "",
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
  form.login = "";
  form.password = "";
  form.timeout_sec = 5;
  form.max_retries = 5;
  showForm.value = true;
}

function openEdit(hook: Webhook) {
  editingId.value = hook.id;
  form.name = hook.name;
  form.url = hook.url;
  form.enabled = hook.enabled;
  form.login = hook.login;
  form.password = "";
  form.timeout_sec = hook.timeout_sec;
  form.max_retries = hook.max_retries;
  showForm.value = true;
}

function closeForm() {
  showForm.value = false;
}

async function saveHook() {
  const url = form.url.trim();
  const login = form.login.trim();
  const password = form.password.trim();
  if (!url) return;
  if (!editingId.value && (!login || password.length < 8)) {
    store.error = "Укажите логин и пароль (минимум 8 символов) для входящего API";
    return;
  }
  if (editingId.value && password && password.length < 8) {
    store.error = "Пароль минимум 8 символов";
    return;
  }
  savingHook.value = true;
  try {
    const body = {
      name: form.name.trim() || "webhook",
      url,
      enabled: form.enabled,
      login,
      password: password ? password : editingId.value ? null : "",
      timeout_sec: Number(form.timeout_sec) || 5,
      max_retries: Number(form.max_retries) || 0,
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
        <p class="lede">Клипы и глобальный выключатель HTTP.</p>
      </div>
      <div class="card-body form-grid">
        <div><SwitchField id="http-sink" v-model="store.settings.enable_http_sink" label="Отправка по HTTP" /></div>
        <div><SwitchField id="clip-record" v-model="store.settings.enable_clip_record" label="Ring-buffer клипов" /></div>
      </div>
      <div class="card-foot end">
        <button type="submit" :disabled="store.saving">Сохранить</button>
      </div>
    </form>

    <section class="card">
      <div class="card-head">
        <h2>Входящий API</h2>
        <p class="lede">
          Django и другие сервисы пушат камеры сюда. В заголовке — логин и пароль webhook’а (HTTP Basic).
        </p>
      </div>
      <div class="card-body">
        <p class="delivery-line">
          <code>Authorization: Basic base64(login:password)</code>
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Метод</th>
                <th>Путь</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>GET</td>
                <td class="uri">/api/v1/cameras</td>
                <td>список</td>
              </tr>
              <tr>
                <td>POST</td>
                <td class="uri">/api/v1/cameras</td>
                <td>создать или обновить</td>
              </tr>
              <tr>
                <td>POST</td>
                <td class="uri">/api/v1/cameras/test-batch</td>
                <td>тестовые камеры (count + ссылка)</td>
              </tr>
              <tr>
                <td>PUT</td>
                <td class="uri">/api/v1/cameras/{id}</td>
                <td>создать или обновить</td>
              </tr>
              <tr>
                <td>PATCH</td>
                <td class="uri">/api/v1/cameras/{id}</td>
                <td>частично</td>
              </tr>
              <tr>
                <td>DELETE</td>
                <td class="uri">/api/v1/cameras/{id}</td>
                <td>удалить</td>
              </tr>
            </tbody>
          </table>
        </div>
        <pre class="code-sample">POST /api/v1/cameras
Authorization: Basic base64(login:password)
Content-Type: application/json

{
  "id": "cam_gate",
  "name": "Калитка",
  "rtsp_url": "rtsp://user:pass@10.0.0.12/stream1",
  "enabled": true,
  "external_id": "42",
  "stream_protocol": 2,
  "resolution_width": 1280,
  "resolution_height": 720,
  "fps": 25,
  "allow_preprocessing": false,
  "usage_modules": [2]
}</pre>
      </div>
      <div class="card-foot end">
        <button type="button" class="ghost" @click="openNew">Добавить webhook</button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Webhook’и ({{ hooks.length }})</h2>
      </div>
      <div class="card-body">
        <div v-if="hooks.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>URL</th>
                <th>Логин</th>
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
                <td>{{ hook.login || "—" }}</td>
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
          <p class="lede">Логин и пароль партнёр передаёт в Authorization: Basic при запросах камер.</p>
        </div>
        <div class="card-body form-grid">
          <Field id="wh-name" v-model="form.name" label="Имя" />
          <Field
            id="wh-url"
            v-model="form.url"
            class="span-2"
            label="URL"
            addon="POST"
            required
            hint="Campus: /api/v1/school/incident-ingest/"
          />
          <Field id="wh-login" v-model="form.login" label="Логин" :required="!editingId" autocomplete="username" />
          <Field
            id="wh-password"
            v-model="form.password"
            label="Пароль"
            type="password"
            :required="!editingId"
            autocomplete="new-password"
            :hint="editingId ? 'Пусто = не менять' : 'Минимум 8 символов'"
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
