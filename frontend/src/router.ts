import { createRouter, createWebHistory } from "vue-router";
import { api } from "./api";
import AdminLayout from "./layouts/AdminLayout.vue";
import CamerasView from "./views/CamerasView.vue";
import CameraFormView from "./views/CameraFormView.vue";
import HistoryView from "./views/HistoryView.vue";
import IngestView from "./views/IngestView.vue";
import LoginView from "./views/LoginView.vue";
import NodeView from "./views/NodeView.vue";
import OverviewView from "./views/OverviewView.vue";
import TriggersView from "./views/TriggersView.vue";
import UsersView from "./views/UsersView.vue";
import UserFormView from "./views/UserFormView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView },
    {
      path: "/",
      component: AdminLayout,
      meta: { auth: true },
      children: [
        { path: "", name: "overview", component: OverviewView },
        { path: "cameras", name: "cameras", component: CamerasView },
        { path: "cameras/new", name: "camera-new", component: CameraFormView },
        { path: "cameras/:id", name: "camera-edit", component: CameraFormView },
        { path: "settings", name: "settings", component: NodeView },
        { path: "node", redirect: { name: "settings" } },
        { path: "ingest", name: "ingest", component: IngestView },
        { path: "triggers", name: "triggers", component: TriggersView },
        { path: "history", name: "history", component: HistoryView },
        { path: "users", name: "users", component: UsersView },
        { path: "users/new", name: "user-new", component: UserFormView },
        { path: "users/:id", name: "user-edit", component: UserFormView },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  try {
    const session = await api.session();
    if (to.matched.some((record) => record.meta.auth) && !session.authenticated) {
      return { name: "login" };
    }
    if (session.authenticated && !session.license_valid && to.name !== "settings" && to.name !== "login") {
      return { name: "settings" };
    }
    if (to.name === "login" && session.authenticated) {
      return { name: session.license_valid ? "overview" : "settings" };
    }
  } catch {
    if (to.name !== "login") {
      return { name: "login" };
    }
  }
  return true;
});
