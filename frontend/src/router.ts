import { createRouter, createWebHashHistory } from "vue-router";
export const navigation = [
  { id: "documents", label: "医学资料库", icon: "▤" },
  { id: "reader", label: "资料阅读器", icon: "▧" },
  { id: "ask", label: "依据问答", icon: "✧" },
  { id: "graph", label: "知识图谱", icon: "⌘" },
  { id: "relations", label: "关系与出处", icon: "↗" },
  { id: "generate", label: "智能出题", icon: "＋" },
  { id: "teaching", label: "蓝图与病例", icon: "▦" },
  { id: "bank", label: "题库与审核", icon: "✓" },
  { id: "study", label: "练习与复习", icon: "◷" },
  { id: "evaluations", label: "效果评测", icon: "▥" },
  { id: "traces", label: "运行与回放", icon: "↺" },
  { id: "settings", label: "模型与设置", icon: "⚙" },
];
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/evaluations",
      name: "evaluations",
      component: () => import("./components/EvaluationsView.vue"),
    },
    {
      path: "/traces",
      name: "traces",
      component: () => import("./components/TracesView.vue"),
    },
    {
      path: "/teaching",
      name: "teaching",
      component: () => import("./components/TeachingView.vue"),
    },
    {
      path: "/study",
      name: "study",
      component: () => import("./components/StudyView.vue"),
    },
    {
      path: "/relations",
      name: "relations",
      component: () => import("./components/RelationsView.vue"),
    },
    { path: "/", redirect: "/ask" },
    {
      path: "/ask",
      name: "ask",
      component: () => import("./components/AskView.vue"),
    },
    {
      path: "/documents",
      name: "documents",
      component: () => import("./components/DocumentsView.vue"),
    },
    {
      path: "/reader/:id?",
      name: "reader",
      component: () => import("./components/ReaderView.vue"),
    },
    {
      path: "/generate",
      name: "generate",
      component: () => import("./components/GenerateView.vue"),
    },
    {
      path: "/bank",
      name: "bank",
      component: () => import("./components/BankView.vue"),
    },
    {
      path: "/graph",
      name: "graph",
      component: () => import("./components/GraphView.vue"),
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("./components/SettingsView.vue"),
    },
    { path: "/:pathMatch(.*)*", redirect: "/ask" },
  ],
});
