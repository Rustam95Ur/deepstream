<script setup lang="ts">
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import {
  PRESETS,
  SCHOOL_ALGORITHMS,
  algorithmIsOn,
  presetIsActive,
  selectedAlgorithmCount,
  setAlgorithm,
  triggersFromAlgorithms,
} from "../schoolAlgorithms";
import { saveSettings, store } from "../store";

function currentTriggers(): string[] {
  return store.settings?.enabled_triggers ?? [];
}

function isOn(id: string) {
  return algorithmIsOn(currentTriggers(), id);
}

function setOn(id: string, on: boolean) {
  if (!store.settings) return;
  store.settings.enabled_triggers = setAlgorithm(currentTriggers(), id, on);
}

function applyPreset(id: string) {
  if (!store.settings) return;
  const preset = PRESETS.find((item) => item.id === id);
  if (!preset) return;
  store.settings.enabled_triggers = triggersFromAlgorithms(preset.algorithms);
}

function fightOn() {
  return isOn("fight");
}
</script>

<template>
  <form v-if="store.settings" class="stack-lg" @submit.prevent="saveSettings">
    <section class="card">
      <div class="card-head">
        <h2>Сценарии</h2>
        <p class="lede">
          Галочка включает алгоритм на ноде. У падения и курения модели пока нет —
          пункт сохранится, сработок не будет, пока не подключим веса.
        </p>
      </div>
      <div class="card-body">
        <div class="preset-row">
          <button
            v-for="preset in PRESETS"
            :key="preset.id"
            type="button"
            class="ghost"
            :class="{ on: presetIsActive(currentTriggers(), preset.id) }"
            :title="preset.hint"
            @click="applyPreset(preset.id)"
          >
            {{ preset.label }}
          </button>
        </div>
        <p class="lede preset-count">
          Выбрано {{ selectedAlgorithmCount(currentTriggers()) }} из {{ SCHOOL_ALGORITHMS.length }}
        </p>
        <table class="algo-table">
          <thead>
            <tr>
              <th>Категория</th>
              <th>Алгоритм</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="opt in SCHOOL_ALGORITHMS" :key="opt.id">
              <td class="muted">{{ opt.category }}</td>
              <td>
                <div class="algo-cell">
                  <SwitchField
                    :id="`trig-${opt.id}`"
                    :model-value="isOn(opt.id)"
                    :label="opt.ready ? opt.label : `${opt.label} · скоро`"
                    @update:model-value="(v) => setOn(opt.id, v)"
                  />
                  <p class="lede">{{ opt.hint }}</p>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Пороги</h2>
        <p class="lede">Общие пауза и клип. Остальное — только для включённых сценариев.</p>
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
        <template v-if="fightOn()">
          <Field
            id="min-tracks"
            v-model="store.settings.min_tracks"
            label="Мин. людей (сходка)"
            hint="Минимум людей в кадре, чтобы считать сходку или пересечение."
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
          <Field
            id="vif-iou"
            v-model="store.settings.vif_iou_thresh"
            label="Порог пересечения"
            hint="Насколько сильно боксы людей должны пересечься."
            type="number"
            step="0.01"
          />
          <Field
            id="vif-sus"
            v-model="store.settings.vif_sustain_s"
            label="Удержание пересечения, сек"
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
            hint="Нет кадров дольше этого — событие «камера молчит»."
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
