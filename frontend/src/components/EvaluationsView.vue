<script setup lang="ts">
import { onActivated, ref } from "vue";
import { api, send } from "../api";
import type { DocumentInfo, Evidence } from "../types";
import EvidenceList from "./EvidenceList.vue";
type Sample = {
  query: string;
  expected_evidence_ids: string[];
  reference_answer: string;
};
type Suite = { id: string; name: string; samples: Sample[]; reviewed: number };
type Result = {
  sample_index: number;
  query: string;
  mode: string;
  effective_mode: string;
  available: boolean;
  recall: number | null;
  reciprocal_rank: number | null;
  seconds: number;
  evidence: Evidence[];
  warnings: string[];
  human_rating: {
    evidence_support: boolean | null;
    answer_correct: boolean | null;
    note: string;
  } | null;
};
type Run = {
  id: string;
  suite_id: string;
  created_at: string;
  report: {
    top_k: number;
    source_revision: string;
    suite_reviewed: boolean;
    message: string;
    results: Result[];
    metrics?: {
      mode: string;
      available_samples: number;
      total_samples: number;
      mean_recall: number | null;
      mrr: number | null;
      mean_seconds: number | null;
    }[];
  };
};
const suites = ref<Suite[]>([]),
  runs = ref<Run[]>([]),
  documents = ref<DocumentInfo[]>([]),
  chunks = ref<Evidence[]>([]),
  documentId = ref(""),
  title = ref(""),
  samples = ref<Sample[]>([
    { query: "", expected_evidence_ids: [], reference_answer: "" },
  ]),
  error = ref(""),
  busy = ref(false),
  modes = ref(["keyword", "graph", "hybrid"]),
  message = ref(""),
  topK = ref(5),
  active = ref<Run | null>(null);
async function load() {
  [suites.value, runs.value, documents.value] = await Promise.all([
    api("/evaluations"),
    api("/evaluation-runs"),
    api("/documents"),
  ]);
  if (active.value)
    active.value =
      runs.value.find((r) => r.id === active.value?.id) || active.value;
}
async function choose() {
  chunks.value = (
    await api<DocumentInfo>("/documents/" + documentId.value)
  ).chunks;
}
async function perform(action: () => Promise<unknown>) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "评测失败";
  } finally {
    busy.value = false;
  }
}
async function save() {
  await perform(async () => {
    await send("/evaluations", { name: title.value, samples: samples.value });
    message.value = "评测集已保存为未人工确认。";
  });
}
async function run(id: string) {
  await perform(async () => {
    const r = await send(`/evaluations/${id}/run`, {
      modes: modes.value,
      top_k: topK.value,
    });
    active.value = { ...r, suite_id: id, created_at: new Date().toISOString() };
  });
}
async function rate(result: Result) {
  if (!active.value) return;
  await perform(() =>
    send(`/evaluation-runs/${active.value!.id}/rate`, {
      sample_index: result.sample_index,
      mode: result.mode,
      ...result.human_rating,
    }),
  );
}
onActivated(() => load().catch((e) => (error.value = e.message)));
</script>
<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">MEASURE · COMPARE · REVIEW</p>
      <h1>让改造效果有真实对照</h1>
      <p>固定资料和问题，比较关键词、向量、审核关系和融合检索。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="message" class="notice success">{{ message }}</p>
  <section class="panel stack">
    <h2>建立固定评测集</h2>
    <form class="stack" @submit.prevent="save">
      <label>评测集名称<input v-model="title" required maxlength="200" /></label
      ><label
        >从资料选择预期证据<select
          aria-label="从资料选择预期证据"
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
      >
      <article v-for="(sample, i) in samples" :key="i" class="chunk stack">
        <div class="section-title">
          <h3>问题 {{ i + 1 }}</h3>
          <button
            class="text-button danger"
            type="button"
            :disabled="samples.length === 1"
            @click="samples.splice(i, 1)"
          >
            移除问题
          </button>
        </div>
        <label
          >固定问题<input
            v-model="sample.query"
            required
            maxlength="1000" /></label
        ><label
          >预期依据（可多选）<select
            aria-label="预期依据（可多选）"
            v-model="sample.expected_evidence_ids"
            multiple
            required
          >
            <option v-for="c in chunks" :key="c.id" :value="c.id">
              {{ c.location }} {{ c.text.slice(0, 60) }}
            </option>
          </select></label
        ><label
          >人工参考答案<textarea
            v-model="sample.reference_answer"
            maxlength="4000"
          ></textarea>
        </label>
      </article>
      <div class="inline">
        <button
          class="secondary"
          type="button"
          :disabled="samples.length >= 100"
          @click="
            samples.push({
              query: '',
              expected_evidence_ids: [],
              reference_answer: '',
            })
          "
        >
          增加问题</button
        ><button
          class="primary"
          :disabled="
            busy || samples.some((s) => !s.expected_evidence_ids.length)
          "
        >
          保存评测集
        </button>
      </div>
    </form>
  </section>
  <section class="panel stack section-gap">
    <h2>运行对照</h2>
    <div class="inline">
      <label
        v-for="mode in ['keyword', 'vector', 'graph', 'hybrid']"
        :key="mode"
        class="check-label"
        ><input v-model="modes" type="checkbox" :value="mode" />{{
          mode
        }}</label
      ><label
        >返回条数<input v-model.number="topK" type="number" min="1" max="10"
      /></label>
    </div>
    <article v-for="suite in suites" :key="suite.id" class="chunk">
      <div class="section-title">
        <h3>{{ suite.name }} · {{ suite.samples.length }} 个问题</h3>
        <span class="tag">{{
          suite.reviewed ? "已由人工确认" : "尚未人工确认"
        }}</span>
      </div>
      <div class="inline">
        <button
          class="primary"
          :disabled="busy || !modes.length"
          @click="run(suite.id)"
        >
          运行检索对照</button
        ><button
          class="secondary"
          :disabled="busy"
          @click="
            perform(() =>
              send(`/evaluations/${suite.id}/review`, {
                reviewed: !suite.reviewed,
              }),
            )
          "
        >
          {{ suite.reviewed ? "撤销人工确认" : "确认问题和预期证据" }}
        </button>
      </div>
      <details>
        <summary>查看固定问题与参考答案</summary>
        <div v-for="(sample, i) in suite.samples" :key="i">
          <p>{{ sample.query }}</p>
          <blockquote>
            {{ sample.reference_answer || "未提供参考答案" }}
          </blockquote>
        </div>
      </details>
    </article>
    <p class="help">
      人工确认是本机审核记录；系统不核验审核者的专业资质。缺少向量索引会显示“未运行”，不冒充关键词对照结果。
    </p>
  </section>
  <section class="panel stack section-gap">
    <h2>历史对照记录</h2>
    <select
      :value="active?.id || ''"
      aria-label="评测记录"
      @change="
        active =
          runs.find(
            (r) => r.id === ($event.target as HTMLSelectElement).value,
          ) || null
      "
    >
      <option value="">选择评测记录</option>
      <option v-for="r in runs" :key="r.id" :value="r.id">
        {{ new Date(r.created_at).toLocaleString() }} ·
        {{ suites.find((s) => s.id === r.suite_id)?.name }}
      </option></select
    ><template v-if="active"
      ><div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>模式</th>
              <th>可运行样本</th>
              <th>平均召回率</th>
              <th>MRR</th>
              <th>平均耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="metric in active.report.metrics || []"
              :key="metric.mode"
            >
              <td>{{ metric.mode }}</td>
              <td>
                {{ metric.available_samples }} / {{ metric.total_samples }}
              </td>
              <td>
                {{
                  metric.mean_recall === null
                    ? "未运行"
                    : (metric.mean_recall * 100).toFixed(1) + "%"
                }}
              </td>
              <td>{{ metric.mrr?.toFixed(3) ?? "未运行" }}</td>
              <td>{{ metric.mean_seconds?.toFixed(3) ?? "未运行" }} 秒</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="help">{{ active.report.message }}</p>
      <p>
        资料版本 {{ active.report.source_revision.slice(0, 12) }} · 返回
        {{ active.report.top_k }} 条
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>问题</th>
              <th>请求 / 实际模式</th>
              <th>召回率</th>
              <th>倒数排名</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in active.report.results"
              :key="r.sample_index + r.mode"
            >
              <td>{{ r.query }}</td>
              <td>{{ r.mode }} / {{ r.effective_mode }}</td>
              <td>
                {{
                  r.recall === null
                    ? "未运行"
                    : (r.recall * 100).toFixed(1) + "%"
                }}
              </td>
              <td>{{ r.reciprocal_rank?.toFixed(3) ?? "未运行" }}</td>
              <td>{{ r.seconds.toFixed(3) }} 秒</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details
        v-for="r in active.report.results"
        :key="r.sample_index + r.mode"
      >
        <summary>{{ r.query }} · {{ r.mode }} · 核对检索与人工评价</summary>
        <p v-for="w in r.warnings" :key="w" class="notice">{{ w }}</p>
        <EvidenceList :items="r.evidence" /><button
          v-if="!r.human_rating"
          class="secondary"
          @click="
            r.human_rating = {
              evidence_support: null,
              answer_correct: null,
              note: '',
            }
          "
        >
          填写人工评价
        </button>
        <form v-if="r.human_rating" class="stack" @submit.prevent="rate(r)">
          <label
            >证据是否支持问题<select
              aria-label="证据是否支持问题"
              v-model="r.human_rating.evidence_support"
            >
              <option :value="null">未判定</option>
              <option :value="true">支持</option>
              <option :value="false">不支持</option>
            </select></label
          ><label
            >人工另行核对的答案是否正确<select
              aria-label="人工另行核对的答案是否正确"
              v-model="r.human_rating.answer_correct"
            >
              <option :value="null">未评答案</option>
              <option :value="true">正确</option>
              <option :value="false">错误</option>
            </select></label
          ><label
            >评价依据与实际答案<textarea
              v-model="r.human_rating.note"
              maxlength="2000"
              placeholder="若评价答案，请附实际答案、来源与理由"
            ></textarea></label
          ><button class="secondary" :disabled="busy">保存人工评价</button>
        </form>
      </details></template
    >
  </section>
</template>
