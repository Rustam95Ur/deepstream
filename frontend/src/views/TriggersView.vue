<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { saveSettings, store } from "../store";

const OPTIONS = [
  { id: "presence", label: "Присутствие", hint: "В кадре достаточно людей дольше порога." },
  { id: "convergence", label: "Схождение", hint: "Люди сблизились на кадре." },
  { id: "vif", label: "VIF", hint: "Боксы людей сильно пересеклись." },
  { id: "stream_silent", label: "Тишина потока", hint: "С камеры нет кадров дольше порога." },
] as const;

function isOn(id: string) {
  const list = store.settings?.enabled_triggers;
  if (!list) return true;
  return list.includes(id);
}

function setOn(id: string, on: boolean) {
  if (!store.settings) return;
  const next = new Set(store.settings.enabled_triggers ?? OPTIONS.map((t) => t.id));
  if (on) next.add(id);
  else next.delete(id);
  store.settings.enabled_triggers = OPTIONS.map((t) => t.id).filter((item) => next.has(item));
}
</script>

<template>
  <form v-if="store.settings" class="stack-lg" @submit.prevent="saveSettings">
    <section class="card">
      <div class="card-head">
        <h2>События</h2>
        <p class="lede">Выключенные типы не пишутся в историю и не отправляются по HTTP.</p>
      </div>
      <div class="card-body trigger-list">
        <div v-for="opt in OPTIONS" :key="opt.id" class="trigger-row">
          <SwitchField
            :id="`trig-${opt.id}`"
            :model-value="isOn(opt.id)"
            :label="opt.label"
            @update:model-value="(v) => setOn(opt.id, v)"
          />
          <p class="lede">{{ opt.hint }}</p>
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Пороги</h2>
        <p class="lede">Общие пауза и клип. Остальное — только для включённых событий.</p>
      </div>
      <div class="card-body form-grid">
        <Field
          id="cooldown"
          v-model="store.settings.cooldown_s"
          label="Пауза между сработками, сек"
          hint="Повтор того же типа с этой камеры не уйдёт раньше этой паузы."
          type="number"
          step="0.1"
        />
        <Field
          id="conf"
          v-model="store.settings.conf_threshold"
          label="Порог уверенности"
          hint="Боксы детектора ниже этого score отбрасываются."
          type="number"
          step="0.01"
        />
        <Field
          id="clip-pre"
          v-model="store.settings.clip_pre_s"
          label="Клип до события, сек"
          hint="Сколько секунд ring-buffer взять до момента сработки."
          type="number"
          step="0.1"
        />
        <Field
          id="clip-post"
          v-model="store.settings.clip_post_s"
          label="Клип после события, сек"
          hint="Сколько секунд после сработки дописать в клип."
          type="number"
          step="0.1"
        />

        <template v-if="isOn('presence')">
          <Field
            id="presence-min"
            v-model="store.settings.presence_min_people"
            label="Мин. людей (присутствие)"
            hint="Сколько человек должно быть в кадре одновременно."
            type="number"
          />
          <Field
            id="presence-sus"
            v-model="store.settings.presence_sustain_s"
            label="Удержание присутствия, сек"
            hint="Сколько секунд подряд держать это число людей."
            type="number"
            step="0.1"
          />
        </template>
        <template v-if="isOn('convergence')">
          <Field
            id="min-tracks"
            v-model="store.settings.min_tracks"
            label="Мин. треков"
            hint="Минимум людей в кадре, чтобы вообще считать схождение."
            type="number"
          />
          <Field
            id="converge"
            v-model="store.settings.converge_dist_bh"
            label="Дистанция схождения"
            hint="Насколько близко люди (в высотах бокса), чтобы считать «рядом»."
            type="number"
            step="0.1"
          />
          <Field
            id="sustain"
            v-model="store.settings.sustain_s"
            label="Удержание схождения, сек"
            hint="Сколько секунд держать сближение, прежде чем слать событие."
            type="number"
            step="0.1"
          />
        </template>
        <template v-if="isOn('vif')">
          <Field
            id="vif-iou"
            v-model="store.settings.vif_iou_thresh"
            label="Порог IoU"
            hint="Насколько сильно боксы людей должны пересечься."
            type="number"
            step="0.01"
          />
          <Field
            id="vif-sus"
            v-model="store.settings.vif_sustain_s"
            label="Удержание IoU, сек"
            hint="Сколько секунд держать пересечение боксов."
            type="number"
            step="0.1"
          />
        </template>
        <template v-if="isOn('stream_silent')">
          <Field
            id="silent"
            v-model="store.settings.stream_silent_s"
            label="Тишина потока, сек"
            hint="Нет кадров дольше этого — событие «тишина потока»."
            type="number"
            step="0.1"
          />
        </template>
      </div>
      <div class="card-foot end">
        <button type="submit" :disabled="store.saving">Сохранить</button>
      </div>
    </section>
  </form>
</template>
