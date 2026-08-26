<script setup lang="ts">
import { onMounted } from "vue";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import {
  SCHOOL_ALGORITHMS,
  algorithmIsOn,
  selectedAlgorithmCount,
  setAlgorithm,
} from "../schoolAlgorithms";
import { ensureTriggerProfiles, profileField, setProfileField } from "../triggerThresholds";
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

function fightOn() {
  return isOn("fight");
}

function pf(kind: "presence" | "convergence" | "vif" | "stream_silent", key: string) {
  if (!store.settings) return 0;
  return profileField(store.settings, kind, key);
}

function setPf(
  kind: "presence" | "convergence" | "vif" | "stream_silent",
  key: string,
  value: number,
) {
  if (!store.settings) return;
  setProfileField(store.settings, kind, key, value);
}

onMounted(() => {
  if (store.settings) {
    store.settings = ensureTriggerProfiles(store.settings);
  }
});
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
        <p class="lede algo-count">
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
        <h2>Общие параметры</h2>
        <p class="lede">Детектор и клип — для всех сценариев. Пороги ниже — отдельно для каждого типа.</p>
      </div>
      <div class="card-body form-grid">
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
      </div>
    </section>

    <section v-if="isOn('presence')" class="card">
      <div class="card-head">
        <h2>Присутствие</h2>
        <p class="lede">Свои пороги для сценария «Присутствие».</p>
      </div>
      <div class="card-body form-grid">
        <Field
          id="presence-min"
          :model-value="pf('presence', 'presence_min_people')"
          label="Мин. людей"
          hint="Сколько человек должно быть в кадре одновременно."
          type="number"
          @update:model-value="(v) => setPf('presence', 'presence_min_people', Number(v))"
        />
        <Field
          id="presence-sus"
          :model-value="pf('presence', 'presence_sustain_s')"
          label="Удержание, сек"
          hint="Сколько секунд подряд держать это число людей."
          type="number"
          step="0.1"
          @update:model-value="(v) => setPf('presence', 'presence_sustain_s', Number(v))"
        />
        <Field
          id="presence-cooldown"
          :model-value="pf('presence', 'cooldown_s')"
          label="Пауза между сработками, сек"
          type="number"
          step="0.1"
          @update:model-value="(v) => setPf('presence', 'cooldown_s', Number(v))"
        />
      </div>
    </section>

    <template v-if="fightOn()">
      <section class="card">
        <div class="card-head">
          <h2>Драка — сходка</h2>
          <p class="lede">Пороги для trigger type <code>convergence</code>.</p>
        </div>
        <div class="card-body form-grid">
          <Field
            id="min-tracks"
            :model-value="pf('convergence', 'min_tracks')"
            label="Мин. людей"
            hint="Минимум людей в кадре, чтобы считать сходку."
            type="number"
            @update:model-value="(v) => setPf('convergence', 'min_tracks', Number(v))"
          />
          <Field
            id="converge"
            :model-value="pf('convergence', 'converge_dist_bh')"
            label="Дистанция схождения"
            hint="Насколько близко люди (в высотах бокса), чтобы считать «рядом»."
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('convergence', 'converge_dist_bh', Number(v))"
          />
          <Field
            id="speed"
            :model-value="pf('convergence', 'speed_thresh_bh')"
            label="Порог сближения"
            hint="Насколько быстро люди должны сближаться."
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('convergence', 'speed_thresh_bh', Number(v))"
          />
          <Field
            id="sustain"
            :model-value="pf('convergence', 'sustain_s')"
            label="Удержание, сек"
            hint="Сколько секунд держать сближение, прежде чем слать событие."
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('convergence', 'sustain_s', Number(v))"
          />
          <Field
            id="convergence-cooldown"
            :model-value="pf('convergence', 'cooldown_s')"
            label="Пауза между сработками, сек"
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('convergence', 'cooldown_s', Number(v))"
          />
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>Драка — пересечение</h2>
          <p class="lede">Пороги для trigger type <code>vif</code> (пересечение боксов).</p>
        </div>
        <div class="card-body form-grid">
          <Field
            id="vif-iou"
            :model-value="pf('vif', 'vif_iou_thresh')"
            label="Порог пересечения"
            hint="Насколько сильно боксы людей должны пересечься."
            type="number"
            step="0.01"
            @update:model-value="(v) => setPf('vif', 'vif_iou_thresh', Number(v))"
          />
          <Field
            id="vif-sus"
            :model-value="pf('vif', 'vif_sustain_s')"
            label="Удержание, сек"
            hint="Сколько секунд держать пересечение боксов."
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('vif', 'vif_sustain_s', Number(v))"
          />
          <Field
            id="vif-cooldown"
            :model-value="pf('vif', 'cooldown_s')"
            label="Пауза между сработками, сек"
            type="number"
            step="0.1"
            @update:model-value="(v) => setPf('vif', 'cooldown_s', Number(v))"
          />
        </div>
      </section>
    </template>

    <section v-if="isOn('stream_silent')" class="card">
      <div class="card-head">
        <h2>Камера молчит</h2>
        <p class="lede">Свои пороги для технического сценария «тишина потока».</p>
      </div>
      <div class="card-body form-grid">
        <Field
          id="silent"
          :model-value="pf('stream_silent', 'stream_silent_s')"
          label="Тишина потока, сек"
          hint="Нет кадров дольше этого — событие «камера молчит»."
          type="number"
          step="0.1"
          @update:model-value="(v) => setPf('stream_silent', 'stream_silent_s', Number(v))"
        />
        <Field
          id="silent-cooldown"
          :model-value="pf('stream_silent', 'cooldown_s')"
          label="Пауза между сработками, сек"
          type="number"
          step="0.1"
          @update:model-value="(v) => setPf('stream_silent', 'cooldown_s', Number(v))"
        />
      </div>
    </section>

    <div class="card-foot end">
      <button type="submit" :disabled="store.saving">Сохранить</button>
    </div>
  </form>
</template>
