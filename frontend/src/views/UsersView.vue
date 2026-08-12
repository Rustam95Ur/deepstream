<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import Field from "../components/Field.vue";
import Pager from "../components/Pager.vue";
import { ApiError, api } from "../api";
import { PAGE_SIZE, useCursorPage } from "../cursorPage";
import { flash, store } from "../store";
import type { User, UserQuery } from "../types";

const router = useRouter();
const users = ref<User[]>([]);
const totalCount = ref(0);
const pendingDelete = ref<User | null>(null);
const loading = ref(false);
const { cursor, canPrev, canNext, resetPage, setNext, goNext, goPrev } = useCursorPage();
const filters = reactive({
  q: "",
  from: "",
  to: "",
});

function dayStart(date: string) {
  return new Date(`${date}T00:00:00`).toISOString();
}

function dayEnd(date: string) {
  return new Date(`${date}T23:59:59.999`).toISOString();
}

function query(): UserQuery {
  return {
    q: filters.q.trim() || undefined,
    since: filters.from ? dayStart(filters.from) : undefined,
    until: filters.to ? dayEnd(filters.to) : undefined,
    cursor: cursor.value || undefined,
    limit: PAGE_SIZE,
  };
}

async function loadUsers() {
  loading.value = true;
  store.error = "";
  try {
    const data = await api.users(query());
    users.value = data.users;
    totalCount.value = data.total ?? totalCount.value;
    setNext(data.next_cursor);
    if (!users.value.length && goPrev()) {
      await loadUsers();
    }
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось загрузить пользователей";
  } finally {
    loading.value = false;
  }
}

function applyFilters() {
  resetPage();
  void loadUsers();
}

function resetFilters() {
  filters.q = "";
  filters.from = "";
  filters.to = "";
  applyFilters();
}

function nextPage() {
  if (goNext()) void loadUsers();
}

function prevPage() {
  if (goPrev()) void loadUsers();
}

async function confirmDelete() {
  const user = pendingDelete.value;
  if (!user) return;
  try {
    await api.deleteUser(user.id);
    pendingDelete.value = null;
    flash("Пользователь удалён");
    await loadUsers();
  } catch (err) {
    store.error = err instanceof ApiError ? err.message : "Не удалось удалить";
  }
}

onMounted(() => {
  void loadUsers();
});
</script>

<template>
  <div class="stack-lg">
    <form class="card" @submit.prevent="applyFilters">
      <div class="card-head">
        <h2>Фильтры</h2>
        <p class="lede">Запрос уходит на сервер. Пустые поля не учитываются.</p>
      </div>
      <div class="card-body form-grid">
        <Field id="user-q" v-model="filters.q" label="Поиск" />
        <Field id="user-from" v-model="filters.from" label="С даты" type="date" />
        <Field id="user-to" v-model="filters.to" label="До даты" type="date" />
      </div>
      <div class="card-foot end">
        <div class="row">
          <button type="submit" :disabled="loading">{{ loading ? "Загрузка…" : "Применить" }}</button>
          <button type="button" class="ghost" :disabled="loading" @click="resetFilters">Сбросить</button>
        </div>
      </div>
    </form>

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
                      :disabled="u.id === store.session?.user_id || totalCount <= 1"
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
          <p class="empty-title">{{ loading ? "Загрузка…" : "Пользователей не найдено" }}</p>
          <p class="lede">Измените фильтры или добавьте оператора кнопкой выше.</p>
        </div>
      </div>
      <div v-if="canPrev || canNext" class="card-foot end">
        <Pager
          :can-prev="canPrev"
          :can-next="canNext"
          :disabled="loading"
          @prev="prevPage"
          @next="nextPage"
        />
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
