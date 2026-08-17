<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import {
  STREAM_PROTOCOLS,
  USAGE_MODULES,
  cameraProfile,
  cameraProfileMeta,
} from "../cameraProfile";
import {
  NODE_TRIGGERS,
  SCHOOL_ALGORITHMS,
  algorithmIsOn,
  setAlgorithm,
} from "../schoolAlgorithms";
import { flash, refreshCameras, refreshWorker, store } from "../store";

const route = useRoute();
const router = useRouter();
const isNew = computed(() => route.name === "camera-new");
const cameraId = computed(() => String(route.params.id || ""));
const missing = ref(false);

const form = reactive({
  id: "",
  name: "",
  main_uri: "",
  stream_protocol: 2,
  resolution_width: 1280,
  resolution_height: 720,
  fps: 25,
  enabled: true,
  allow_preprocessing: false,
  usage_modules: [2] as number[],
  inheritTriggers: true,
  enabled_triggers: [...NODE_TRIGGERS] as string[],
});

function applyCamera(cam: (typeof store.cameras)[number]) {
  const profile = cameraProfile(cam);
  form.id = cam.id;
  form.name = cam.name;
  form.main_uri = cam.main_uri;
  form.stream_protocol = profile.stream_protocol;
  form.resolution_width = profile.resolution_width;
  form.resolution_height = profile.resolution_height;
  form.fps = profile.fps;
  form.enabled = cam.enabled;
  form.allow_preprocessing = profile.allow_preprocessing;
  form.usage_modules = Array.isArray(cam.meta?.usage_modules) ? profile.usage_modules : [2];
  form.inheritTriggers = cam.enabled_triggers == null;
  form.enabled_triggers = cam.enabled_triggers ?? [...NODE_TRIGGERS];
}

onMounted(async () => {
  if (isNew.value) return;
  let cam = store.cameras.find((c) => c.id === cameraId.value);
  if (!cam) {
    try {
      await refreshCameras();
      cam = store.cameras.find((c) => c.id === cameraId.value);
    } catch (err) {
      store.error = err instanceof ApiError ? err.message : "Не удалось загрузить камеру";
      missing.value = true;
      return;
    }
  }
  if (!cam) {
    missing.value = true;
    return;
  }
  applyCamera(cam);
});

function isOn(id: string) {
  return algorithmIsOn(form.enabled_triggers, id);
}

function setOn(id: string, on: boolean) {
  form.enabled_triggers = setAlgorithm(form.enabled_triggers, id, on);
}

function hasModule(id: number) {
  return form.usage_modules.includes(id);
}

function setModule(id: number, on: boolean) {
  if (on) {
    if (!form.usage_modules.includes(id)) form.usage_modules = [...form.usage_modules, id];
    return;
  }
  form.usage_modules = form.usage_modules.filter((item) => item !== id);
}

function selectedTriggers() {
  return form.inheritTriggers ? null : form.enabled_triggers;
}

function profileFields() {
  return cameraProfileMeta({
    stream_protocol: Number(form.stream_protocol) || 2,
    resolution_width: Number(form.resolution_width) || 1280,
    resolution_height: Number(form.resolution_height) || 720,
    fps: Number(form.fps) || 25,
    allow_preprocessing: form.allow_preprocessing,
    usage_modules: form.usage_modules,
  });
}

async function onSubmit() {
  const uri = form.main_uri.trim();
  if (!uri) return;
  try {
    if (isNew.value) {
      const id = form.id.trim() || `cam_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
      await api.upsertCamera({
        id,
        name: form.name.trim() || id,
        main_uri: uri,
        enabled: form.enabled,
        enabled_triggers: selectedTriggers(),
        ...profileFields(),
      });
      flash("Камера сохранена");
    } else {
      const cam = store.cameras.find((c) => c.id === cameraId.value);
      if (!cam) return;
      await api.updateCamera(cam.id, {
        ...cam,
        name: form.name.trim() || cam.id,
        main_uri: uri,
        enabled: form.enabled,
        enabled_triggers: selectedTriggers(),
        meta: { ...cam.meta, ...profileFields() },
      });
      flash("Камера обновлена");
    }
    await refreshCameras();
    await refreshWorker().catch(() => undefined);
    await router.push({ name: "cameras" });
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось сохранить камеру";
  }
}
</script>

<template>
  <form v-if="!missing" class="card" @submit.prevent="onSubmit">
    <div class="card-head">
      <h2>{{ isNew ? "Новая камера" : "Изменить камеру" }}</h2>
      <p class="lede">
        Поля как в Campus. Класс и привязка к устройству остаются в Campus.
      </p>
    </div>
    <div class="card-body form-grid">
      <Field
        id="cam-id"
        v-model="form.id"
        label="DeepStream camera id"
        addon="ID"
        :readonly="!isNew"
      />
      <Field id="cam-name" v-model="form.name" label="Название" addon="Имя" />
      <Field
        id="cam-uri"
        v-model="form.main_uri"
        class="span-2"
        label="RTSP ссылка"
        addon="rtsp://"
        required
      />
      <div class="ig">
        <label class="form-label" for="cam-proto">Протокол потока</label>
        <div class="form-floating">
          <select id="cam-proto" v-model.number="form.stream_protocol" required>
            <option v-for="opt in STREAM_PROTOCOLS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>
      </div>
      <Field id="cam-fps" v-model="form.fps" label="Кадров в секунду" type="number" required />
      <Field id="cam-w" v-model="form.resolution_width" label="Ширина разрешения" type="number" required />
      <Field id="cam-h" v-model="form.resolution_height" label="Высота разрешения" type="number" required />
      <div class="span-2 switch-cell">
        <SwitchField id="cam-enabled" v-model="form.enabled" label="Активен" />
      </div>
      <div class="span-2 switch-cell">
        <SwitchField
          id="cam-pre"
          v-model="form.allow_preprocessing"
          label="Разрешить предварительную обработку"
        />
      </div>
      <div class="span-2">
        <p class="form-label">Модули использования</p>
        <div class="check-set">
          <label v-for="mod in USAGE_MODULES" :key="mod.value">
            <input
              :id="`cam-mod-${mod.value}`"
              type="checkbox"
              :checked="hasModule(mod.value)"
              @change="setModule(mod.value, ($event.target as HTMLInputElement).checked)"
            />
            {{ mod.label }}
          </label>
        </div>
      </div>
      <div class="span-2 switch-cell">
        <SwitchField id="cam-inherit" v-model="form.inheritTriggers" label="Сценарии — как у ноды" />
      </div>
      <div v-if="!form.inheritTriggers" class="span-2 trigger-list">
        <div v-for="opt in SCHOOL_ALGORITHMS" :key="opt.id" class="trigger-row">
          <SwitchField
            :id="`cam-trig-${opt.id}`"
            :model-value="isOn(opt.id)"
            :label="opt.ready ? opt.label : `${opt.label} · скоро`"
            @update:model-value="(v) => setOn(opt.id, v)"
          />
          <p class="lede">{{ opt.hint }}</p>
        </div>
      </div>
    </div>
    <div class="card-foot end">
      <div class="row">
        <button type="submit">{{ isNew ? "Добавить" : "Сохранить" }}</button>
        <button type="button" class="ghost" @click="router.push({ name: 'cameras' })">Отмена</button>
      </div>
    </div>
  </form>
  <section v-else class="card">
    <div class="card-head">
      <h2>Камера не найдена</h2>
      <p class="lede">Запись удалена или идентификатор неверный.</p>
    </div>
    <div class="card-foot end">
      <button type="button" class="ghost" @click="router.push({ name: 'cameras' })">К списку</button>
    </div>
  </section>
</template>
