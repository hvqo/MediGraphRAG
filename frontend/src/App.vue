<script setup>
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { api } from "./api";
const views = {
  ask: defineAsyncComponent(() => import("./components/AskView.vue")),
  documents: defineAsyncComponent(
    () => import("./components/DocumentsView.vue"),
  ),
  generate: defineAsyncComponent(() => import("./components/GenerateView.vue")),
  bank: defineAsyncComponent(() => import("./components/BankView.vue")),
  graph: defineAsyncComponent(() => import("./components/GraphView.vue")),
  settings: defineAsyncComponent(() => import("./components/SettingsView.vue")),
};
const navigation = [
  { id: "ask", label: "依据问答", icon: "✧" },
  { id: "documents", label: "医学资料库", icon: "▤" },
  { id: "generate", label: "智能出题", icon: "＋" },
  { id: "bank", label: "题库与审核", icon: "✓" },
  { id: "graph", label: "知识图谱", icon: "⌘" },
  { id: "settings", label: "模型与设置", icon: "⚙" },
];
const view = ref("ask"),
  status = ref(null),
  documents = ref([]),
  questions = ref([]),
  error = ref("");
const active = computed(() =>
  navigation.find((item) => item.id === view.value),
);
const pending = computed(
  () => questions.value.filter((q) => q.status === "pending_review").length,
);
async function refresh() {
  try {
    [status.value, documents.value, questions.value] = await Promise.all([
      api("/status"),
      api("/documents"),
      api("/questions"),
    ]);
    error.value = "";
  } catch (e) {
    error.value = "无法连接后端服务，请先启动应用。";
  }
}
function navigate(id) {
  if (views[id]) view.value = id;
}
onMounted(refresh);
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="navigate('ask')"
        ><svg
          width="38"
          height="38"
          viewBox="0 0 38 38"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M10 10L28 11L19 28L10 10ZM10 10L8 27L19 28"
            stroke="currentColor"
            stroke-width="2"
          />
          <circle cx="10" cy="10" r="4" fill="currentColor" />
          <circle cx="28" cy="11" r="4" fill="currentColor" />
          <circle cx="19" cy="28" r="4" fill="currentColor" />
          <circle cx="8" cy="27" r="3" fill="currentColor" /></svg
        ><span>MediGraph<em>RAG</em><small>医学知识与出题平台</small></span></a
      >
      <p class="nav-caption">工作空间</p>
      <nav aria-label="主导航">
        <button
          v-for="item in navigation"
          :key="item.id"
          :class="{ active: view === item.id }"
          :aria-current="view === item.id ? 'page' : undefined"
          @click="navigate(item.id)"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span
          >{{ item.label
          }}<span
            v-if="item.id === 'bank' && pending"
            class="nav-count"
            aria-hidden="true"
            >{{ pending }}</span
          >
        </button>
      </nav>
      <div class="sidebar-bottom">
        <span class="status-dot" :class="{ offline: !status }"></span
        >{{ status ? "服务已连接" : "等待服务连接"
        }}<small>以资料为依据，以审核保障质量</small>
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <span
          >医学教育工作台
          <span class="breadcrumb">/ {{ active.label }}</span></span
        ><span class="provider-badge"
          ><span class="status-dot"></span
          >{{ status?.provider === "cloud" ? "云端模型" : "本地 Ollama" }}</span
        >
      </header>
      <main>
        <div v-if="error" class="notice error" role="alert">
          {{ error }}
          <button class="text-button" @click="refresh">重试连接</button>
        </div>
        <div class="workspace-stats">
          <span
            ><strong>{{ documents.length }}</strong> 份医学资料</span
          ><span
            ><strong>{{
              documents.reduce((n, d) => n + d.chunk_count, 0)
            }}</strong>
            个原文片段</span
          ><span
            ><strong>{{ pending }}</strong> 道题待审核</span
          >
        </div>
        <KeepAlive
          ><component :is="views[view]" @navigate="navigate" @changed="refresh"
        /></KeepAlive>
      </main>
      <footer>MEDIGRAPH RAG <span>医学学习 · 原文追溯 · 人工审题</span></footer>
    </div>
  </div>
</template>
