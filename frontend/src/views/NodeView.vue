<script setup lang="ts">
import { onMounted, ref } from "vue";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { loadConsole, saveSettings, store } from "../store";
import type { BillingCheck } from "../types";

const check = ref<BillingCheck | null>(null);
const checking = ref(false);

const reasonLabels: Record<string, string> = {
  missing_api_key: "ключ не задан",
  not_checked: "ещё не проверялся",
  key_not_found: "ключ не найден",
  client_inactive: "клиент отключён",
  subscription_expired: "подписка истекла",
  stolen_key: "ключ привязан к другой плате",
  invalid: "ключ отклонён",
};

function reasonText(row: BillingCheck) {
  if (row.valid) return "ключ действителен";
  const base = reasonLabels[row.reason] || row.reason || "нет статуса";
  if (row.destroy) return `${base} — контейнеры будут удалены`;
  return base;
}

function checkedAt(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

async function loadBilling() {
  try {
    check.value = await api.billing();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить статус лицензии";
  }
}

async function validateBilling() {
  if (!store.settings) return;
  checking.value = true;
  try {
    check.value = await api.validateBilling({
      billing_url: store.settings.billing_url,
      billing_api_key: store.settings.billing_api_key,
    });
    store.session = await api.session();
    if (check.value.valid) {
      store.error = "";
      await loadConsole();
    } else {
      store.cameras = [];
      store.worker = null;
      store.error = store.session.license_reason || "Лицензия недействительна";
    }
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось проверить ключ";
  } finally {
    checking.value = false;
  }
}

onMounted(() => {
  void loadBilling();
});
</script>

<template>
  <div v-if="store.settings" class="stack-lg">
    <form class="card" @submit.prevent="saveSettings">
      <div class="card-head">
        <h2>Идентификация</h2>
        <p class="lede">Имя ноды и лимит потоков. Вход в консоль по email.</p>
      </div>
      <div class="card-body form-grid">
        <Field id="node-id" v-model="store.settings.node_id" label="Идентификатор" required />
        <Field id="node-name" v-model="store.settings.node_name" label="Название" />
        <Field id="max-streams" v-model="store.settings.max_streams" label="Макс. потоков" type="number" />
        <div class="switch-cell">
          <SwitchField id="auto-start" v-model="store.settings.auto_start_pipeline" label="Автозапуск pipeline" />
        </div>
      </div>
      <div class="card-foot end">
        <button type="submit" :disabled="store.saving">Сохранить</button>
      </div>
    </form>

    <form class="card" @submit.prevent="saveSettings">
      <div class="card-head">
        <h2>Nexus Billing</h2>
        <p class="lede">Проверка API-ключа в Nexus Billing.</p>
      </div>
      <div class="card-body form-grid">
        <Field
          id="billing-url"
          v-model="store.settings.billing_url"
          label="URL проверки"
          hint="POST /api/v1/public/keys/validate"
        />
        <Field
          id="billing-key"
          v-model="store.settings.billing_api_key"
          type="password"
          label="API-ключ"
          autocomplete="off"
        />
      </div>
      <div class="card-foot end">
        <div class="row">
          <span v-if="check" class="muted">
            <span class="badge" :class="check.valid ? 'badge-ok' : 'badge-warn'">
              {{ reasonText(check) }}
            </span>
            <span v-if="check.client_name"> {{ check.client_name }}</span>
            <span v-if="check.module"> · {{ check.module }}</span>
            <span v-if="check.checked_at"> · {{ checkedAt(check.checked_at) }}</span>
          </span>
          <button type="button" class="ghost" :disabled="checking" @click="validateBilling">
            {{ checking ? "Проверка…" : "Проверить ключ" }}
          </button>
          <button type="submit" :disabled="store.saving">Сохранить</button>
        </div>
      </div>
    </form>
  </div>
</template>
