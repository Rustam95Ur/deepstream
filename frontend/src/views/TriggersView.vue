<script setup lang="ts">
import Field from "../components/Field.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
    <div class="card-head">
      <h2>Пороги</h2>
      <p class="lede">Те же ключи, что в API settings.</p>
    </div>
    <div class="card-body form-grid">
      <Field id="cooldown" v-model="store.settings.cooldown_s" label="cooldown_s" type="number" step="0.1" />
      <Field id="presence-min" v-model="store.settings.presence_min_people" label="presence_min_people" type="number" />
      <Field id="presence-sus" v-model="store.settings.presence_sustain_s" label="presence_sustain_s" type="number" step="0.1" />
      <Field id="min-tracks" v-model="store.settings.min_tracks" label="min_tracks" type="number" />
      <Field id="converge" v-model="store.settings.converge_dist_bh" label="converge_dist_bh" type="number" step="0.1" />
      <Field id="sustain" v-model="store.settings.sustain_s" label="sustain_s" type="number" step="0.1" />
      <Field id="vif-iou" v-model="store.settings.vif_iou_thresh" label="vif_iou_thresh" type="number" step="0.01" />
      <Field id="vif-sus" v-model="store.settings.vif_sustain_s" label="vif_sustain_s" type="number" step="0.1" />
      <Field id="clip-pre" v-model="store.settings.clip_pre_s" label="clip_pre_s" type="number" step="0.1" />
      <Field id="clip-post" v-model="store.settings.clip_post_s" label="clip_post_s" type="number" step="0.1" />
      <Field id="conf" v-model="store.settings.conf_threshold" label="conf_threshold" type="number" step="0.01" />
    </div>
    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
