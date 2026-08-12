<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Field from "../components/Field.vue";
import Logo from "../components/Logo.vue";
import { ApiError, api } from "../api";
import type { Session } from "../types";

const router = useRouter();
const session = ref<Session | null>(null);
const email = ref("");
const password = ref("");
const passwordConfirm = ref("");
const error = ref("");
const pending = ref(false);

onMounted(async () => {
  session.value = await api.session();
});

async function onSubmit() {
  error.value = "";
  pending.value = true;
  try {
    await api.login(email.value, password.value, passwordConfirm.value);
    await router.push({ name: "overview" });
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "Не удалось войти";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-form-col">
      <div class="auth-card">
        <template v-if="session">
          <h1>{{ session.setup ? "Доступ" : "Вход" }}</h1>
          <p class="lede">
            {{ session.setup ? "Создайте первого пользователя по email." : "Вход в консоль по email." }}
          </p>
          <p class="muted auth-node">{{ session.node_name }} · {{ session.node_id }}</p>
          <form class="auth-form" autocomplete="on" @submit.prevent="onSubmit">
            <Field
              id="email"
              v-model="email"
              label="Email"
              type="email"
              autocomplete="username"
              required
              :invalid="!!error"
            />
            <Field
              id="password"
              v-model="password"
              label="Пароль"
              type="password"
              :autocomplete="session.setup ? 'new-password' : 'current-password'"
              :minlength="session.setup ? 8 : undefined"
              required
              :invalid="!!error"
            />
            <Field
              v-if="session.setup"
              id="password_confirm"
              v-model="passwordConfirm"
              label="Повтор пароля"
              type="password"
              autocomplete="new-password"
              :minlength="8"
              required
              :invalid="!!error"
            />
            <p v-if="error" class="field-error" role="alert">{{ error }}</p>
            <button type="submit" :disabled="pending">
              {{ session.setup ? "Создать и войти" : "Войти" }}
            </button>
          </form>
        </template>
      </div>
    </div>
    <aside class="auth-aside">
      <div class="logo-wrap">
        <Logo :height="44" inverse />
      </div>
      <h2>Nexus DeepStream</h2>
      <p>Консоль ноды: камеры, pipeline и пороги на одном экране.</p>
    </aside>
  </main>
</template>
