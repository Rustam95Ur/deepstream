<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
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
</template>
