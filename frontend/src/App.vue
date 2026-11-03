<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { navigation, primaryNavigation, moreNavigation } from "./router";
import { useWorkspace } from "./stores/workspace";
import { api } from "./api";
const route = useRoute(),
  router = useRouter(),
  workspace = useWorkspace();
const { status, summary, error } = storeToRefs(workspace);
const view = computed(() => String(route.name || "ask"));
const active = computed(
  () => navigation.find((item) => item.id === view.value) || navigation[0],
);
const pending = computed(() => summary.value.pending);
const profile = ref(null as { name: string } | null);
const moreOpen = ref(false);
watch(
  () => route.name,
  (name) => {
    if (name !== "reader" && moreNavigation.some((item) => item.id === name))
      moreOpen.value = true;
  },
  { immediate: true },
);
const refresh = () => workspace.refresh();
function navigate(id: string) {
  if (router.hasRoute(id)) router.push({ name: id });
}
onMounted(async () => {
  try {
    profile.value = await api("/profile");
  } catch {}
  await refresh();
});
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
      <small class="profile-label"
        >{{ profile?.name || "个人资料库" }} · 自动保存</small
      >
      <nav aria-label="主导航">
        <button
          v-for="item in primaryNavigation"
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
      <details
        class="tool-menu"
        :open="moreOpen"
        @toggle="moreOpen = ($event.target as HTMLDetailsElement).open"
      >
        <summary>更多工具</summary>
        <nav aria-label="教学与管理工具">
          <button
            v-for="item in moreNavigation"
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
      </details>
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
            ><strong>{{ summary.documents }}</strong> 份医学资料</span
          ><span
            ><strong>{{ summary.chunks }}</strong> 个原文片段</span
          ><span
            ><strong>{{ pending }}</strong> 道题待审核</span
          >
        </div>
        <RouterView v-slot="{ Component }"
          ><KeepAlive
            ><component
              :is="Component"
              :key="$route.name"
              @navigate="navigate"
              @changed="refresh" /></KeepAlive
        ></RouterView>
      </main>
      <footer>MEDIGRAPH RAG <span>医学学习 · 原文追溯 · 人工审题</span></footer>
    </div>
  </div>
</template>
