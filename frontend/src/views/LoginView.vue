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
const otpToken = ref("");
const otpQr = ref("");
const otpKey = ref("");
const error = ref("");
const pending = ref(false);

function afterLogin(sess: Session) {
  if (sess.otp_pending) return;
  void router.push({ name: sess.license_valid ? "overview" : "settings" });
}

async function loadOtpSetup() {
  const data = await api.otpSetup();
  otpQr.value = data.qr_data_uri;
  otpKey.value = data.manual_key;
}

async function showSession(sess: Session) {
  session.value = sess;
  if (sess.otp_pending && sess.otp_setup) await loadOtpSetup();
  afterLogin(sess);
}

onMounted(async () => {
  const sess = await api.session();
  session.value = sess;
  if (sess.otp_pending && sess.otp_setup) await loadOtpSetup();
});

async function onSubmit() {
  error.value = "";
  pending.value = true;
  try {
    await showSession(await api.login(email.value, password.value, passwordConfirm.value));
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "Не удалось войти";
  } finally {
    pending.value = false;
  }
}

async function onOtp() {
  if (!session.value) return;
  error.value = "";
  pending.value = true;
  try {
    const sess = session.value.otp_setup
      ? await api.confirmOtp(otpToken.value)
      : await api.verifyOtp(otpToken.value);
    await showSession(sess);
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "Неверный код";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-form-col">
      <div class="auth-card">
        <template v-if="session?.otp_pending">
          <h1>{{ session.otp_setup ? "Подключите аутентификатор" : "Код из аутентификатора" }}</h1>
          <p class="lede">
            {{
              session.otp_setup
                ? "Отсканируйте QR в Google Authenticator и введите первый код."
                : "Введите 6-значный код из Google Authenticator."
            }}
          </p>
          <form class="auth-form" @submit.prevent="onOtp">
            <img v-if="session.otp_setup && otpQr" class="otp-qr" :src="otpQr" alt="QR-код Google Authenticator" />
            <p v-if="session.otp_setup && otpKey" class="muted otp-key">Ключ: <code>{{ otpKey }}</code></p>
            <Field id="otp" v-model="otpToken" label="Код" autocomplete="one-time-code" required :invalid="!!error" />
            <p v-if="error" class="field-error" role="alert">{{ error }}</p>
            <button type="submit" :disabled="pending">{{ pending ? "Проверка…" : "Подтвердить" }}</button>
          </form>
        </template>
        <template v-else-if="session">
          <h1>{{ session.setup ? "Доступ" : "Вход" }}</h1>
          <p class="lede">
            {{ session.setup ? "Создайте первого оператора ноды по email." : "Сотрудник входит учётной записью Nexus." }}
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

<style scoped>
.otp-qr {
  width: 180px;
  height: 180px;
  justify-self: center;
}
.otp-key {
  margin: 0;
  text-align: center;
  overflow-wrap: anywhere;
}
</style>
