<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
    <div class="card-head">
      <h2>Интеграции</h2>
      <p class="lede">Campus или другой backend. Поля можно оставить пустыми.</p>
    </div>
    <div class="card-body form-grid">
      <Field id="cameras-url" v-model="store.settings.cameras_url" class="span-2" label="cameras_url" addon="GET" />
      <Field id="poll-sec" v-model="store.settings.cameras_poll_sec" label="cameras_poll_sec" type="number" />
      <Field id="triggers-url" v-model="store.settings.triggers_url" class="span-2" label="triggers_url" addon="POST" />
      <div><SwitchField id="http-sink" v-model="store.settings.enable_http_sink" label="HTTP sink" /></div>
      <div><SwitchField id="celery-sink" v-model="store.settings.enable_celery_sink" label="Celery sink" /></div>
      <Field id="celery-url" v-model="store.settings.celery_broker_url" class="span-2" label="celery_broker_url" />
    </div>
    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
