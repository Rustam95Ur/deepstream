<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
    <div class="card-head">
      <h2>Интеграции</h2>
      <p class="lede">Внешний сервер и клип инцидента. Поля URL можно оставить пустыми.</p>
    </div>
    <div class="card-body form-grid">
      <Field id="cameras-url" v-model="store.settings.cameras_url" class="span-2" label="URL списка камер" addon="GET" />
      <Field id="poll-sec" v-model="store.settings.cameras_poll_sec" label="Интервал опроса, сек" type="number" />
      <Field id="triggers-url" v-model="store.settings.triggers_url" class="span-2" label="URL триггеров" addon="POST" />
      <div><SwitchField id="http-sink" v-model="store.settings.enable_http_sink" label="Отправка по HTTP" /></div>
      <div><SwitchField id="clip-record" v-model="store.settings.enable_clip_record" label="Ring-buffer клипов (как rtsp_writer)" /></div>
    </div>
    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
