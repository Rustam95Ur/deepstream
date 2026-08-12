<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import Field from "../components/Field.vue";
import SwitchField from "../components/SwitchField.vue";
import { ApiError, api } from "../api";
import { flash, refreshCameras, store } from "../store";

const route = useRoute();
const router = useRouter();
const isNew = computed(() => route.name === "camera-new");
const cameraId = computed(() => String(route.params.id || ""));
const missing = ref(false);

const form = reactive({
  id: "",
  name: "",
  main_uri: "",
  enabled: true,
});

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
  form.id = cam.id;
  form.name = cam.name;
  form.main_uri = cam.main_uri;
  form.enabled = cam.enabled;
});

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
      });
      flash("Камера обновлена");
    }
    await refreshCameras();
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
        {{ isNew ? "Пустой идентификатор выдаётся автоматически." : "Идентификатор нельзя сменить — поток привязан к нему." }}
      </p>
    </div>
    <div class="card-body form-grid">
      <Field
        id="cam-id"
        v-model="form.id"
        label="Идентификатор"
        addon="ID"
        :readonly="!isNew"
      />
      <Field id="cam-name" v-model="form.name" label="Имя" addon="Имя" />
      <Field id="cam-uri" v-model="form.main_uri" class="span-2" label="Адрес потока" addon="rtsp://" required />
      <div class="span-2 switch-cell">
        <SwitchField id="cam-enabled" v-model="form.enabled" label="Включена" />
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
