<script setup lang="ts">
import { computed, onActivated, ref } from "vue";
import { api, send } from "../api";
import EvidenceList from "./EvidenceList.vue";
import type { Evidence } from "../types";
type Exercise = {
  id: string;
  revision: string;
  topic: string;
  options: Record<string, string>;
  question_type: string;
  knowledge_point: string;
  case_narrative: string;
};
type Feedback = {
  correct: boolean;
  answer: string[];
  analysis: string;
  evidence: Evidence[];
};
type History = {
  attempts: {
    id: string;
    correct: number;
    created_at: string;
    answers: { question: { topic: string }; selected: string[] };
  }[];
  knowledge: {
    knowledge_point: string;
    wrong: number;
    attempts: number;
    evidence: Evidence[];
    recommended_question_ids: string[];
  }[];
};
type Statistics = {
  method: string;
  items: {
    question_id: string;
    topic: string;
    intended_difficulty: string;
    first_attempts: number;
    observed_error_rate: number | null;
    option_rates: Record<string, number> | null;
    discrimination: number | null;
  }[];
};
const learner = ref(
    localStorage.getItem("medigraph-learner") || "我的学习档案",
  ),
  questions = ref<Exercise[]>([]),
  selected = ref(""),
  answers = ref<string[]>([]),
  feedback = ref<Feedback | null>(null),
  history = ref<History | null>(null),
  statistics = ref<Statistics | null>(null),
  error = ref(""),
  busy = ref(false),
  tab = ref("practice");
const current = computed(() =>
  questions.value.find((q) => q.id === selected.value),
);
let started = Date.now();
function choose() {
  feedback.value = null;
  answers.value = [];
  started = Date.now();
}
async function load() {
  error.value = "";
  try {
    [questions.value, history.value, statistics.value] = await Promise.all([
      api("/study/questions"),
      api("/study/history?learner_id=" + encodeURIComponent(learner.value)),
      api("/study/statistics"),
    ]);
    if (
      !selected.value ||
      !questions.value.some((q) => q.id === selected.value)
    ) {
      selected.value = questions.value[0]?.id || "";
      choose();
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "加载失败";
  }
}
async function profile() {
  localStorage.setItem("medigraph-learner", learner.value);
  await load();
}
async function submit() {
  if (!current.value) return;
  busy.value = true;
  error.value = "";
  try {
    feedback.value = await send("/study/attempts", {
      learner_id: learner.value,
      question_id: current.value.id,
      revision: current.value.revision,
      answers: answers.value,
      seconds: Math.min(86400, Math.floor((Date.now() - started) / 1000)),
    });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "提交失败";
  } finally {
    busy.value = false;
  }
}
function recommend(id: string) {
  selected.value = id;
  choose();
  tab.value = "practice";
}
onActivated(load);
</script>
<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">PRACTICE · FEEDBACK · ORIGINAL SOURCE</p>
      <h1>从错题回到知识点</h1>
      <p>练习只使用审核通过且依据有效的题目；提交后查看答案、解析和原文。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <section class="panel stack">
    <div class="inline">
      <label>本机学习档案<input v-model="learner" maxlength="64" /></label
      ><button class="secondary" :disabled="!learner.trim()" @click="profile">
        使用此档案
      </button>
    </div>
    <p class="help">档案仅用于本机区分学习记录，不是登录账户或权限隔离。</p>
    <div class="inline">
      <button
        :class="tab === 'practice' ? 'primary' : 'secondary'"
        @click="tab = 'practice'"
      >
        开始练习</button
      ><button
        :class="tab === 'history' ? 'primary' : 'secondary'"
        @click="tab = 'history'"
      >
        错题与知识点</button
      ><button
        :class="tab === 'statistics' ? 'primary' : 'secondary'"
        @click="tab = 'statistics'"
      >
        教师统计
      </button>
    </div>
  </section>
  <section v-if="tab === 'practice'" class="panel stack section-gap">
    <select v-model="selected" aria-label="练习题目" @change="choose">
      <option v-for="q in questions" :key="q.id" :value="q.id">
        {{ q.knowledge_point }} · {{ q.topic.slice(0, 50) }}
      </option></select
    ><template v-if="current"
      ><blockquote v-if="current.case_narrative">
        {{ current.case_narrative }}
      </blockquote>
      <h2>{{ current.topic }}</h2>
      <fieldset :disabled="!!feedback">
        <legend>
          选择{{
            current.question_type === "multiple_choice"
              ? "全部正确选项"
              : "一个选项"
          }}
        </legend>
        <label
          v-for="(value, key) in current.options"
          :key="key"
          class="option check-label"
          ><input
            v-if="current.question_type === 'multiple_choice'"
            type="checkbox"
            v-model="answers"
            :value="key"
          /><input
            v-else
            type="radio"
            name="exercise-answer"
            :checked="answers[0] === key"
            @change="answers = [String(key)]"
          /><strong>{{ key }}</strong> {{ value }}</label
        >
      </fieldset>
      <button
        class="primary"
        :disabled="busy || !answers.length || !!feedback"
        @click="submit"
      >
        提交并查看解析
      </button>
      <section v-if="feedback" class="stack">
        <h3>
          {{ feedback.correct ? "回答正确" : "这道题需要再复习" }} · 答案
          {{ feedback.answer.join("、") }}
        </h3>
        <p>{{ feedback.analysis }}</p>
        <EvidenceList :items="feedback.evidence" /></section
    ></template>
    <p v-else class="empty">当前没有可练习题目，请先完成题目审核。</p>
  </section>
  <section v-if="tab === 'history'" class="panel stack section-gap">
    <h2>知识点复习</h2>
    <article
      v-for="point in history?.knowledge || []"
      :key="point.knowledge_point"
      class="chunk"
    >
      <h3>{{ point.knowledge_point }}</h3>
      <p>{{ point.attempts }} 次练习，{{ point.wrong }} 次需要复习</p>
      <EvidenceList :items="point.evidence" /><button
        v-for="id in point.recommended_question_ids"
        :key="id"
        class="secondary"
        @click="recommend(id)"
      >
        练习同考点另一题
      </button>
    </article>
    <h2>最近作答</h2>
    <p v-for="attempt in history?.attempts || []" :key="attempt.id">
      {{ attempt.correct ? "✓" : "○" }} {{ attempt.answers.question.topic }} ·
      {{ attempt.answers.selected.join("、") }} ·
      {{ new Date(attempt.created_at).toLocaleString() }}
    </p>
  </section>
  <section v-if="tab === 'statistics'" class="panel stack section-gap">
    <h2>真实作答统计</h2>
    <p class="help">{{ statistics?.method }}</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>题目</th>
            <th>预期难度</th>
            <th>首次人数</th>
            <th>实际错误率</th>
            <th>干扰项选择率</th>
            <th>探索性区分度</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in statistics?.items || []" :key="item.question_id">
            <td>{{ item.topic }}</td>
            <td>{{ item.intended_difficulty }}</td>
            <td>{{ item.first_attempts }}</td>
            <td>
              {{
                item.observed_error_rate === null
                  ? "样本不足"
                  : `${(item.observed_error_rate * 100).toFixed(1)}%`
              }}
            </td>
            <td>
              {{
                item.option_rates
                  ? Object.entries(item.option_rates)
                      .map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`)
                      .join(" / ")
                  : "样本不足"
              }}
            </td>
            <td>{{ item.discrimination ?? "样本不足" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
