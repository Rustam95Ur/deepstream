<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
    <div class="card-head">
      <h2>Идентификация</h2>
      <p class="lede">Токен используется и для UI, и как Bearer для API.</p>
    </div>
    <div class="card-body form-grid">
      <Field id="node-id" v-model="store.settings.node_id" label="node_id" required />
      <Field id="node-name" v-model="store.settings.node_name" label="node_name" />
      <Field id="api-token" v-model="store.settings.api_token" class="span-2" label="API token" type="password" autocomplete="off" />
      <Field id="max-streams" v-model="store.settings.max_streams" label="max_streams" type="number" />
      <div>
        <SwitchField id="auto-start" v-model="store.settings.auto_start_pipeline" label="auto_start_pipeline" />
      </div>
    </div>
    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
