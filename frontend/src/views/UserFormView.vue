<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import Field from "../components/Field.vue";
import { ApiError, api } from "../api";
import { flash, store } from "../store";

const route = useRoute();
const router = useRouter();
const isNew = computed(() => route.name === "user-new");
const userId = computed(() => String(route.params.id || ""));
const missing = ref(false);

const form = reactive({
  email: "",
  name: "",
  password: "",
});

onMounted(async () => {
  if (isNew.value) return;
  try {
    const user = await api.getUser(userId.value);
    form.email = user.email;
    form.name = user.name;
  } catch (err) {
    missing.value = true;
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить пользователя";
  }
});

async function onSubmit() {
  const mail = form.email.trim();
  if (!mail) return;
  if (isNew.value && !form.password) return;
  try {
    if (isNew.value) {
      await api.createUser({
        email: mail,
        name: form.name.trim(),
        password: form.password,
      });
      flash("Пользователь создан");
    } else {
      await api.updateUser(userId.value, {
        email: mail,
        name: form.name.trim(),
        password: form.password,
      });
      flash("Пользователь обновлён");
    }
    await router.push({ name: "users" });
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось сохранить пользователя";
  }
}
</script>

<template>
  <form v-if="!missing" class="card" @submit.prevent="onSubmit">
    <div class="card-head">
      <h2>{{ isNew ? "Новый пользователь" : "Изменить пользователя" }}</h2>
      <p class="lede">
        {{ isNew ? "Вход в консоль — по email и паролю." : "Пустой пароль оставит текущий без изменений." }}
      </p>
    </div>
    <div class="card-body form-grid">
      <Field id="user-email" v-model="form.email" label="Email" type="email" addon="@" required />
      <Field id="user-name" v-model="form.name" label="Имя" addon="Имя" />
      <Field
        id="user-password"
        v-model="form.password"
        class="span-2"
        :label="isNew ? 'Пароль' : 'Новый пароль'"
        type="password"
        autocomplete="new-password"
        :minlength="isNew ? 8 : 0"
        :required="isNew"
      />
    </div>
    <div class="card-foot end">
      <div class="row">
        <button type="submit">{{ isNew ? "Добавить" : "Сохранить" }}</button>
        <button type="button" class="ghost" @click="router.push({ name: 'users' })">Отмена</button>
      </div>
    </div>
  </form>
  <section v-else class="card">
    <div class="card-head">
      <h2>Пользователь не найден</h2>
      <p class="lede">Запись удалена или идентификатор неверный.</p>
    </div>
    <div class="card-foot end">
      <button type="button" class="ghost" @click="router.push({ name: 'users' })">К списку</button>
    </div>
  </section>
</template>
