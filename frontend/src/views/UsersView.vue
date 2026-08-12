<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, api } from "../api";
import { flash, store } from "../store";
import type { User } from "../types";

const router = useRouter();
const users = ref<User[]>([]);
const pendingDelete = ref<User | null>(null);

async function loadUsers() {
  users.value = (await api.users()).users;
}

onMounted(async () => {
  try {
    await loadUsers();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить пользователей";
  }
});

async function confirmDelete() {
  const user = pendingDelete.value;
  if (!user) return;
  try {
    await api.deleteUser(user.id);
    users.value = users.value.filter((u) => u.id !== user.id);
    pendingDelete.value = null;
    flash("Пользователь удалён");
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось удалить";
  }
}
</script>

<template>
  <div class="stack-lg">
    <section class="card">
      <div class="card-head">
        <h2>Пользователи ({{ users.length }})</h2>
        <p class="lede">Нельзя удалить себя и последнего пользователя.</p>
      </div>
      <div class="card-body">
        <div v-if="users.length" class="table-wrap">
          <table>
            <thead>
              <tr><th>Email</th><th>Имя</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="u in users" :key="u.id">
                <td>
                  <code>{{ u.email }}</code>
                  <span v-if="u.id === store.session?.user_id" class="pill">вы</span>
                </td>
                <td>{{ u.name || "—" }}</td>
                <td class="td-action">
                  <div class="row">
                    <button
                      type="button"
                      class="ghost"
                      :aria-label="`Изменить пользователя ${u.email}`"
                      @click="router.push({ name: 'user-edit', params: { id: u.id } })"
                    >Изменить</button>
                    <button
                      type="button"
                      class="ghost danger"
                      :disabled="u.id === store.session?.user_id || users.length <= 1"
                      :aria-label="`Удалить пользователя ${u.email}`"
                      @click="pendingDelete = u"
                    >Удалить</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">
          <p class="empty-title">Пользователей пока нет</p>
          <p class="lede">Добавьте оператора кнопкой выше.</p>
        </div>
      </div>
    </section>

    <div v-if="pendingDelete" class="modal-scrim" @click.self="pendingDelete = null">
      <div class="card modal" role="dialog" aria-modal="true" aria-labelledby="del-user-title">
        <div class="card-head">
          <h2 id="del-user-title">Удалить пользователя?</h2>
        </div>
        <div class="card-body">
          <p class="lede"><code>{{ pendingDelete.email }}</code> больше не сможет войти.</p>
          <div class="row modal-actions">
            <button type="button" class="danger-fill" @click="confirmDelete">Удалить</button>
            <button type="button" class="ghost" @click="pendingDelete = null">Отмена</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
