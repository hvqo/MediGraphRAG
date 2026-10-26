<script setup lang="ts">
import { computed, onActivated, ref } from "vue";
import { API, api, send } from "../api";
import type { DocumentInfo, Evidence, Citation } from "../types";
type Row = {
  chapter: string;
  knowledge_point: string;
  query: string;
  cognition: string;
  question_type: string;
  difficulty: string;
  count: number;
  case_id: string | null;
  generated?: number;
  approved?: number;
  missing?: number;
  duplicate_stems?: number;
};
type Blueprint = { id: string; title: string; rows: Row[] };
type Case = {
  id: string;
  title: string;
  narrative: string;
  citations: Citation[];
  status: string;
  sources_valid: boolean;
};
const blueprints = ref<Blueprint[]>([]),
  cases = ref<Case[]>([]),
  documents = ref<DocumentInfo[]>([]),
  chunks = ref<Evidence[]>([]),
  documentId = ref(""),
  error = ref(""),
  message = ref(""),
  busy = ref(false);
function blank(): Row {
  return {
    chapter: "",
    knowledge_point: "",
    query: "",
    cognition: "understand",
    question_type: "single_choice",
    difficulty: "medium",
    count: 1,
    case_id: null,
  };
}
const title = ref(""),
  rows = ref<Row[]>([blank()]),
  material = ref({ title: "", narrative: "", evidence_id: "", quote: "" });
const total = computed(() =>
  rows.value.reduce((n, r) => n + Number(r.count), 0),
);
const repeated = computed(() =>
  rows.value
    .filter(
      (r, i) =>
        rows.value.findIndex((o) => o.knowledge_point === r.knowledge_point) <
        i,
    )
    .map((r) => r.knowledge_point)
    .filter(Boolean),
);
async function load() {
  [blueprints.value, cases.value, documents.value] = await Promise.all([
    api("/blueprints"),
    api("/cases"),
    api("/documents"),
  ]);
}
async function choose() {
  chunks.value = (
    await api<DocumentInfo>("/documents/" + documentId.value)
  ).chunks;
  material.value.evidence_id = chunks.value[0]?.id || "";
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
async function save() {
  await perform(async () => {
    await send("/blueprints", { title: title.value, rows: rows.value });
    message.value = "蓝图已保存，可检查覆盖矩阵并发起生成。";
  });
}
async function generate(id: string) {
  await perform(async () => {
    const r = await send(`/blueprints/${id}/generate`, {});
    message.value = `已排队 ${r.jobs.length} 个分布任务，在智能出题页查看进度。`;
  });
}
async function saveCase() {
  await perform(async () => {
    await send("/cases", {
      title: material.value.title,
      narrative: material.value.narrative,
      citations: [
        {
          evidence_id: material.value.evidence_id,
          quote: material.value.quote,
        },
      ],
    });
    message.value = "病例材料已保存，审核通过后可用于题组。";
  });
}
onActivated(() => load().catch((e) => (error.value = e.message)));
</script>
<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">PLAN · COVERAGE · SHARED CASE</p>
      <h1>先设计考点，再组织试题</h1>
      <p>章节、认知层次和题型共同决定出题分布；病例题共享经过审核的材料。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="message" class="notice success">{{ message }}</p>
  <section class="panel stack">
    <h2>新建出题蓝图</h2>
    <form class="stack" @submit.prevent="save">
      <label>蓝图名称<input v-model="title" required maxlength="200" /></label>
      <article v-for="(row, i) in rows" :key="i" class="chunk stack">
        <div class="section-title">
          <h3>分布 {{ i + 1 }}</h3>
          <button
            type="button"
            class="text-button danger"
            :disabled="rows.length === 1"
            @click="rows.splice(i, 1)"
          >
            移除此行
          </button>
        </div>
        <div class="form-grid">
          <label>章节<input v-model="row.chapter" maxlength="300" /></label
          ><label
            >知识点<input
              v-model="row.knowledge_point"
              required
              maxlength="200" /></label
          ><label
            >检索与出题要求<input
              v-model="row.query"
              required
              maxlength="1000" /></label
          ><label
            >认知层次<select aria-label="认知层次" v-model="row.cognition">
              <option value="remember">记忆</option>
              <option value="understand">理解</option>
              <option value="apply">应用</option>
              <option value="analyze">分析</option>
            </select></label
          ><label
            >题型<select aria-label="题型" v-model="row.question_type">
              <option value="single_choice">单选</option>
              <option value="multiple_choice">多选</option>
              <option value="case">病例单选</option>
            </select></label
          ><label
            >预期难度<select aria-label="预期难度" v-model="row.difficulty">
              <option value="easy">基础</option>
              <option value="medium">进阶</option>
              <option value="hard">综合</option>
            </select></label
          ><label
            >数量<input
              v-model.number="row.count"
              type="number"
              min="1"
              max="10"
              required /></label
          ><label
            >共享病例<select aria-label="共享病例" v-model="row.case_id">
              <option :value="null">无共享病例</option>
              <option
                v-for="c in cases.filter(
                  (c) => c.status === 'approved' && c.sources_valid,
                )"
                :key="c.id"
                :value="c.id"
              >
                {{ c.title }}
              </option>
            </select></label
          >
        </div>
      </article>
      <p>预计 {{ rows.length }} 项分布，共 {{ total }} 道题</p>
      <p v-if="repeated.length" class="notice">
        重复知识点：{{ repeated.join("、") }}。请核对是否有意跨题型考查。
      </p>
      <div class="inline">
        <button
          type="button"
          class="secondary"
          :disabled="rows.length >= 20"
          @click="rows.push(blank())"
        >
          添加考点分布</button
        ><button class="primary" :disabled="busy || total > 100">
          保存蓝图
        </button>
      </div>
    </form>
  </section>
  <section
    v-for="blueprint in blueprints"
    :key="blueprint.id"
    class="panel stack section-gap"
  >
    <div class="section-title">
      <h2>{{ blueprint.title }}</h2>
      <a
        class="button secondary"
        :href="`${API}/questions/export?blueprint_id=${encodeURIComponent(blueprint.id)}`"
        target="_blank"
        rel="noopener"
        >导出已审核整卷</a
      >
      <button class="primary" :disabled="busy" @click="generate(blueprint.id)">
        按蓝图生成整卷
      </button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>章节 / 考点</th>
            <th>认知 / 题型</th>
            <th>计划</th>
            <th>已生成</th>
            <th>已审核</th>
            <th>空缺</th>
            <th>重复题干</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in blueprint.rows" :key="i">
            <td>{{ row.chapter }} / {{ row.knowledge_point }}</td>
            <td>{{ row.cognition }} / {{ row.question_type }}</td>
            <td>{{ row.count }}</td>
            <td>{{ row.generated }}</td>
            <td>{{ row.approved }}</td>
            <td>{{ row.missing }}</td>
            <td>{{ row.duplicate_stems }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <div class="reader-layout section-gap">
    <section class="panel stack">
      <h2>共享病例材料</h2>
      <form class="stack" @submit.prevent="saveCase">
        <label
          >病例材料标题<input
            v-model="material.title"
            required
            maxlength="200" /></label
        ><label
          >统一情境<textarea
            v-model="material.narrative"
            rows="5"
            required
            minlength="8"
            maxlength="4000"
          ></textarea></label
        ><label
          >病例依据资料<select
            aria-label="病例依据资料"
            v-model="documentId"
            @change="choose"
          >
            <option value="">选择资料</option>
            <option
              v-for="d in documents.filter((d) => d.active)"
              :key="d.id"
              :value="d.id"
            >
              {{ d.title }}
            </option>
          </select></label
        ><label
          >病例依据片段<select
            aria-label="病例依据片段"
            v-model="material.evidence_id"
            required
          >
            <option v-for="c in chunks" :key="c.id" :value="c.id">
              {{ c.location }} {{ c.text.slice(0, 40) }}
            </option>
          </select></label
        >
        <blockquote>
          {{ chunks.find((c) => c.id === material.evidence_id)?.text }}
        </blockquote>
        <label
          >支持情境的逐字原句<textarea
            v-model="material.quote"
            required
            minlength="4"
            maxlength="800"
          ></textarea></label
        ><button class="primary" :disabled="busy || !material.evidence_id">
          保存待审病例
        </button>
      </form>
    </section>
    <section class="panel stack">
      <h2>病例审核</h2>
      <article v-for="c in cases" :key="c.id" class="chunk">
        <strong>{{ c.title }} · {{ c.status }}</strong>
        <p>{{ c.narrative }}</p>
        <blockquote v-for="citation in c.citations" :key="citation.evidence_id">
          {{ citation.quote }}
        </blockquote>
        <p v-if="!c.sources_valid" class="notice error">出处已失效</p>
        <div class="inline">
          <button
            class="secondary"
            :disabled="busy || !c.sources_valid"
            @click="
              perform(() =>
                send(`/cases/${c.id}/review`, { status: 'approved' }),
              )
            "
          >
            确认情境与原文一致</button
          ><button
            class="text-button danger"
            :disabled="busy"
            @click="
              perform(() =>
                send(`/cases/${c.id}/review`, { status: 'rejected' }),
              )
            "
          >
            驳回病例
          </button>
        </div>
      </article>
      <p v-if="!cases.length" class="empty">尚未建立病例材料。</p>
    </section>
  </div>
</template>
