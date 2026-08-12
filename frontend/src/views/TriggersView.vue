<script setup lang="ts">
import Field from "../components/Field.vue";
import { saveSettings, store } from "../store";
</script>

<template>
  <form v-if="store.settings" class="card" @submit.prevent="saveSettings">
    <div class="card-head">
      <h2>Пороги</h2>
      <p class="lede">Пороги детекции и записи клипов.</p>
    </div>
    <div class="card-body form-grid">
      <Field id="cooldown" v-model="store.settings.cooldown_s" label="Пауза между сработками, сек" type="number" step="0.1" />
      <Field id="presence-min" v-model="store.settings.presence_min_people" label="Мин. людей (присутствие)" type="number" />
      <Field id="presence-sus" v-model="store.settings.presence_sustain_s" label="Удержание присутствия, сек" type="number" step="0.1" />
      <Field id="min-tracks" v-model="store.settings.min_tracks" label="Мин. треков" type="number" />
      <Field id="converge" v-model="store.settings.converge_dist_bh" label="Дистанция схождения" type="number" step="0.1" />
      <Field id="sustain" v-model="store.settings.sustain_s" label="Удержание схождения, сек" type="number" step="0.1" />
      <Field id="vif-iou" v-model="store.settings.vif_iou_thresh" label="Порог IoU" type="number" step="0.01" />
      <Field id="vif-sus" v-model="store.settings.vif_sustain_s" label="Удержание IoU, сек" type="number" step="0.1" />
      <Field id="clip-pre" v-model="store.settings.clip_pre_s" label="Клип до события, сек" type="number" step="0.1" />
      <Field id="clip-post" v-model="store.settings.clip_post_s" label="Клип после события, сек" type="number" step="0.1" />
      <Field id="conf" v-model="store.settings.conf_threshold" label="Порог уверенности" type="number" step="0.01" />
    </div>
    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
