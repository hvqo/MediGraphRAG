<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, send } from "../api";
import type { DocumentInfo, Evidence } from "../types";
import EvidenceList from "./EvidenceList.vue";
type Relation = {
  id: string;
  subject: string;
  predicate: string;
  object: string;
  quote: string;
  conditions: string;
  effective_status: string;
  sources_valid: boolean;
  evidence: Evidence | null;
  note: string;
};
const labels: Record<string, string> = {
  pending_review: "待审",
  approved: "已通过",
  rejected: "已驳回",
  outdated: "依据失效",
  literal_verified: "原文提及已核对",
};
const items = ref<Relation[]>([]),
  documents = ref<DocumentInfo[]>([]),
  chunks = ref<Evidence[]>([]),
  documentId = ref(""),
  error = ref(""),
  message = ref(""),
  busy = ref(false),
  paths = ref<Relation[][]>([]),
  query = ref(""),
  note = ref("");
const form = ref({
  subject: "",
  predicate: "",
  object: "",
  evidence_id: "",
  quote: "",
  conditions: "",
});
async function load() {
  items.value = await api("/relations");
  documents.value = await api("/documents");
}
async function choose() {
  const d = await api<DocumentInfo>("/documents/" + documentId.value);
  chunks.value = d.chunks;
  form.value.evidence_id = d.chunks[0]?.id || "";
}
async function perform(action: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "操作失败";
  } finally {
    busy.value = false;
  }
}
async function extract() {
  await perform(async () => {
    const r = await send("/relations/extract", {
      evidence_id: form.value.evidence_id,
    });
    message.value = r.message;
  });
}
async function create() {
  await perform(async () => {
    await send("/relations", form.value);
    message.value = "候选已保存，请核对医学语义后审核。";
  });
}
async function review(item: Relation, status: string) {
  await perform(() =>
    send(`/relations/${item.id}/review`, { status, note: note.value }),
  );
}
async function search() {
  await perform(async () => {
    paths.value = (
      await send("/relations/paths", { query: query.value })
    ).paths;
  });
}
onMounted(() => load().catch((e) => (error.value = e.message)));
</script>
<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">EVIDENCE → REVIEW → RELATION</p>
      <h1>让每条关系都有出处</h1>
      <p>候选提取、人工审核与路径核对。原文共现仍可在知识图谱页浏览。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="message" class="notice success">{{ message }}</p>
  <div class="reader-layout">
    <section class="panel stack">
      <h2>从原文建立候选</h2>
      <label
        >来源资料<select
          aria-label="来源资料"
          v-model="documentId"
          @change="choose"
        >
          <option value="">选择当前资料</option>
          <option
            v-for="d in documents.filter((d) => d.active)"
            :key="d.id"
            :value="d.id"
          >
            {{ d.title }}
          </option>
        </select></label
      ><label
        >来源片段<select aria-label="来源片段" v-model="form.evidence_id">
          <option v-for="c in chunks" :key="c.id" :value="c.id">
            {{ c.location }} {{ c.text.slice(0, 40) }}
          </option>
        </select></label
      >
      <blockquote>
        {{ chunks.find((c) => c.id === form.evidence_id)?.text }}
      </blockquote>
      <button
        class="secondary"
        :disabled="busy || !form.evidence_id"
        @click="extract"
      >
        模型提取候选关系
      </button>
      <form class="stack" @submit.prevent="create">
        <label
          >主体<input v-model="form.subject" required maxlength="100" /></label
        ><label
          >关系<input
            v-model="form.predicate"
            required
            maxlength="100" /></label
        ><label
          >客体<input v-model="form.object" required maxlength="100" /></label
        ><label
          >逐字引句<textarea
            v-model="form.quote"
            required
            minlength="4"
            maxlength="800"
          ></textarea></label
        ><label
          >适用条件与否定信息<textarea
            v-model="form.conditions"
            maxlength="1000"
          ></textarea></label
        ><button class="primary" :disabled="busy || !form.evidence_id">
          保存候选关系
        </button>
      </form>
    </section>
    <section class="panel stack">
      <h2>已审核关系路径</h2>
      <form class="inline" @submit.prevent="search">
        <input v-model="query" placeholder="输入实体名称" required /><button
          class="secondary"
          :disabled="busy"
        >
          查找路径
        </button>
      </form>
      <p class="help">
        最多两条边；每条边独立核对，路径不自动构成新的医学结论。
      </p>
      <article v-for="(path, i) in paths" :key="i" class="chunk">
        <div v-for="edge in path" :key="edge.id">
          <strong
            >{{ edge.subject }} → {{ edge.predicate }} →
            {{ edge.object }}</strong
          >
          <p>{{ edge.conditions }}</p>
          <blockquote>{{ edge.quote }}</blockquote>
          <EvidenceList v-if="edge.evidence" :items="[edge.evidence]" />
        </div>
      </article>
      <button
        class="secondary"
        :disabled="busy"
        @click="
          perform(async () => {
            const r = await send('/relations/sync', {});
            message = `已同步 ${r.synced} 条有效关系`;
          })
        "
      >
        同步已审核关系到 Neo4j
      </button>
    </section>
  </div>
  <section class="panel stack section-gap">
    <h2>候选与审核记录 · {{ items.length }}</h2>
    <label>本次审核说明<input v-model="note" maxlength="1000" /></label>
    <article v-for="item in items" :key="item.id" class="chunk">
      <div class="section-title">
        <strong
          >{{ item.subject }} → {{ item.predicate }} → {{ item.object }}</strong
        ><span class="tag">{{ labels[item.effective_status] }}</span>
      </div>
      <blockquote>{{ item.quote }}</blockquote>
      <p>适用条件：{{ item.conditions || "未注明，请核对原文" }}</p>
      <p class="help">{{ item.note }}</p>
      <EvidenceList v-if="item.evidence" :items="[item.evidence]" />
      <div class="inline">
        <button
          class="secondary"
          :disabled="busy || !item.sources_valid"
          @click="review(item, 'approved')"
        >
          确认关系并通过</button
        ><button
          class="text-button danger"
          :disabled="busy"
          @click="review(item, 'rejected')"
        >
          驳回
        </button>
      </div>
    </article>
    <p v-if="!items.length" class="empty">
      先选择资料，提取或录入第一条带出处的关系。
    </p>
  </section>
</template>
