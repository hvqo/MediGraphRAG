<script setup>
import {
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
} from "vue";
import { api, send } from "../api";
const form = ref({
  query: "",
  question_type: "single_choice",
  difficulty: "medium",
  count: 1,
  chapter: "",
  knowledge_point: "",
  cognition: "understand",
  case_id: null,
});
const jobs = ref([]),
  cases = ref([]),
  error = ref(""),
  busy = ref(false);
const emit = defineEmits(["navigate", "changed"]);
let timer = null,
  completed = "";
const labels = {
  queued: "等待中",
  running: "生成中",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
};
async function load() {
  jobs.value = await api("/jobs");
  cases.value = await api("/cases");
  const current = jobs.value
    .filter((j) => j.status === "completed")
    .map((j) => j.id)
    .join(",");
  if (current !== completed) {
    completed = current;
    emit("changed");
  }
}
async function generate() {
  busy.value = true;
  error.value = "";
  try {
    await send("/questions/generate", form.value);
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function start() {
  if (timer) return;
  load().catch((e) => (error.value = e.message));
  timer = setInterval(() => load().catch(() => {}), 2500);
}
function stop() {
  clearInterval(timer);
  timer = null;
}
onMounted(start);
onActivated(start);
onDeactivated(stop);
onBeforeUnmount(stop);
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">DESIGNED FOR MEDICAL EDUCATION</p>
      <h1>围绕考点，生成有据可审的题目</h1>
      <p>明确题型与难度，让生成、核验和人工审题各有记录。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <div class="two-columns">
    <form class="panel stack" @submit.prevent="generate">
      <h2>出题要求</h2>
      <div class="form-grid">
        <label>章节<input v-model="form.chapter" maxlength="300" /></label
        ><label
          >知识点标签<input
            v-model="form.knowledge_point"
            maxlength="200"
            placeholder="用于覆盖统计和错题复习" /></label
        ><label
          >认知层次<select aria-label="认知层次" v-model="form.cognition">
            <option value="remember">记忆</option>
            <option value="understand">理解</option>
            <option value="apply">应用</option>
            <option value="analyze">分析</option>
          </select></label
        ><label
          >共享病例<select aria-label="共享病例" v-model="form.case_id">
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
      <label
        >知识点或考点<textarea
          v-model="form.query"
          rows="4"
          placeholder="例如：已导入资料中，关于糖尿病诊断指标的知识点"
          maxlength="1000"
          required
        ></textarea>
      </label>
      <div class="form-grid">
        <label
          >题型<select aria-label="题型" v-model="form.question_type">
            <option value="single_choice">单项选择题</option>
            <option value="multiple_choice">多项选择题</option>
            <option value="case">病例情境单选题</option>
          </select></label
        ><label
          >难度<select aria-label="难度" v-model="form.difficulty">
            <option value="easy">基础</option>
            <option value="medium">进阶</option>
            <option value="hard">综合</option>
          </select></label
        ><label
          >题目数量<input
            type="number"
            v-model.number="form.count"
            min="1"
            max="10"
            required
        /></label>
      </div>
      <button class="primary" :disabled="busy || !form.query.trim()">
        {{ busy ? "提交中…" : "开始生成 →" }}
      </button>
      <p class="help">
        需先导入相关资料并配置可用模型。每道题通过自动检查后进入待审题库。
      </p>
    </form>
    <section class="panel workflow">
      <h2>每道题，都经过这些步骤</h2>
      <ol>
        <li>
          <strong>检索原文</strong><span>从资料库中找到与考点相关的片段</span>
        </li>
        <li>
          <strong>构建题目</strong><span>按题型与难度生成题干、选项和解析</span>
        </li>
        <li>
          <strong>检查依据与答案</strong
          ><span>核对引用、答案集合和选项歧义</span>
        </li>
        <li>
          <strong>交给你审核</strong><span>修改、通过或驳回，保留操作记录</span>
        </li>
      </ol>
    </section>
  </div>
  <section class="panel section-gap">
    <div class="section-title">
      <h2>生成任务</h2>
      <button class="text-button" @click="emit('navigate', 'bank')">
        前往题库 →
      </button>
    </div>
    <div v-if="!jobs.length" class="empty">
      <h3>还没有生成任务</h3>
      <p>提交出题要求后，进度和结果会保留在这里。</p>
    </div>
    <article v-for="job in jobs" :key="job.id" class="job">
      <div class="section-title">
        <strong>{{ job.request.query }}</strong
        ><span
          class="tag"
          :class="{
            amber: job.status === 'failed',
            green: job.status === 'completed',
          }"
          >{{ labels[job.status] }}</span
        >
      </div>
      <progress :value="job.progress" max="100"></progress>
      <div class="inline between">
        <span>{{ job.stage }}</span
        ><span class="muted"
          >{{ job.result.question_ids?.length || 0 }} /
          {{ job.request.count }} 题</span
        >
      </div>
      <p v-if="job.error" class="warning-text">{{ job.error }}</p>
      <details v-if="job.result.attempts?.length" class="analysis">
        <summary>查看生成检查记录</summary>
        <ul class="event-list">
          <li v-for="(attempt, index) in job.result.attempts" :key="index">
            第 {{ attempt.question }} 题 · 第 {{ attempt.attempt }} 次尝试 ·
            {{
              attempt.outcome === "passed"
                ? "已通过，进入待审"
                : "已拦截：" + attempt.reason
            }}
          </li>
        </ul>
      </details>
      <small>{{ new Date(job.created_at).toLocaleString("zh-CN") }}</small>
    </article>
  </section>
</template>
