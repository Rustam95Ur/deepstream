import { createRouter, createWebHistory } from "vue-router";
import { api } from "./api";
import AdminLayout from "./layouts/AdminLayout.vue";
import CamerasView from "./views/CamerasView.vue";
import IngestView from "./views/IngestView.vue";
import LoginView from "./views/LoginView.vue";
import NodeView from "./views/NodeView.vue";
import OverviewView from "./views/OverviewView.vue";
import TriggersView from "./views/TriggersView.vue";

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
        { path: "node", name: "node", component: NodeView },
        { path: "ingest", name: "ingest", component: IngestView },
        { path: "triggers", name: "triggers", component: TriggersView },
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
    if (to.name === "login" && session.authenticated) {
      return { name: "overview" };
    }
  } catch {
    if (to.name !== "login") {
      return { name: "login" };
    }
  }
  return true;
});
