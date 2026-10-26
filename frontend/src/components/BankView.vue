<script setup>
import { computed, onActivated, onMounted, ref } from "vue";
import { API, api, send } from "../api";
import EvidenceList from "./EvidenceList.vue";
const items = ref([]),
  error = ref(""),
  filter = ref("all"),
  keyword = ref(""),
  editing = ref(null),
  events = ref({}),
  notes = ref({}),
  busy = ref(false);
const emit = defineEmits(["changed"]);
const labels = {
  pending_review: "待审核",
  approved: "已通过",
  rejected: "已驳回",
};
const visible = computed(() =>
  items.value.filter(
    (q) =>
      (filter.value === "all" || q.status === filter.value) &&
      q.content.topic.includes(keyword.value),
  ),
);
async function load() {
  try {
    items.value = await api("/questions");
  } catch (e) {
    error.value = e.message;
  }
}
async function review(item, status) {
  busy.value = true;
  error.value = "";
  try {
    await send(`/questions/${item.id}/review`, {
      status,
      note: notes.value[item.id] || "",
    });
    await load();
    emit("changed");
    events.value = {};
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function edit(item) {
  editing.value = {
    id: item.id,
    content: JSON.parse(JSON.stringify(item.content)),
  };
}
async function save() {
  busy.value = true;
  error.value = "";
  try {
    await send("/questions/" + editing.value.id, editing.value.content, "PUT");
    editing.value = null;
    await load();
    emit("changed");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function history(item) {
  try {
    events.value[item.id] = events.value[item.id]
      ? null
      : await api(`/questions/${item.id}/events`);
  } catch (e) {
    error.value = e.message;
  }
}
onMounted(load);
onActivated(load);
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">REVIEW BEFORE RELEASE</p>
      <h1>把好题，留在题库里</h1>
      <p>检查原文、答案与解析。修改后重新审核，保留每一次处理记录。</p>
    </div>
    <div class="inline">
      <a class="button secondary" :href="`${API}/questions/export?format=json`"
        >导出 JSON</a
      ><a class="button primary" :href="`${API}/questions/export?format=csv`"
        >导出 CSV ↓</a
      >
    </div>
  </section>
  <p class="help">
    导出仅包含原文仍有效、且已人工审核通过的题目。列表显示最近 500 道题。
  </p>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <div class="toolbar">
    <input
      v-model="keyword"
      placeholder="搜索题干"
      aria-label="搜索题干"
    /><select v-model="filter" aria-label="审核状态">
      <option value="all">全部状态</option>
      <option value="pending_review">待审核</option>
      <option value="approved">已通过</option>
      <option value="rejected">已驳回</option></select
    ><span class="muted">{{ visible.length }} 道题</span
    ><button class="text-button" @click="load">刷新</button>
  </div>
  <div v-if="!visible.length" class="panel empty section-gap">
    <h3>这里还没有题目</h3>
    <p>先生成题目，或调整筛选条件。</p>
  </div>
  <article
    v-for="item in visible"
    :key="item.id"
    class="panel question-card section-gap"
  >
    <div class="section-title">
      <span
        class="tag"
        :class="item.status === 'approved' ? 'green' : 'amber'"
        >{{ labels[item.status] }}</span
      ><span class="muted"
        >{{
          { single_choice: "单选", multiple_choice: "多选", case: "病例单选" }[
            item.content.question_type
          ]
        }}
        ·
        {{
          { easy: "基础", medium: "进阶", hard: "综合" }[
            item.content.difficulty
          ]
        }}</span
      >
    </div>
    <h2 class="question-topic">{{ item.content.topic }}</h2>
    <div class="options">
      <div
        v-for="(text, key) in item.content.options"
        :key="key"
        class="option"
        :class="{ correct: item.content.answer.includes(key) }"
      >
        <span>{{ key }}</span
        >{{ text }}
      </div>
    </div>
    <details class="analysis">
      <summary>答案与解析 · {{ item.content.answer.join("、") }}</summary>
      <p>{{ item.content.analysis }}</p>
    </details>
    <details class="analysis">
      <summary>核对原文依据</summary>
      <EvidenceList :items="item.evidence" />
      <blockquote
        v-for="citation in item.content.citations"
        :key="citation.evidence_id"
      >
        {{ citation.quote }}
      </blockquote>
    </details>
    <blockquote v-if="item.metadata.case_narrative">
      共享病例：{{ item.metadata.case_narrative }}
    </blockquote>
    <p class="help">
      考点：{{ item.metadata.knowledge_point || "未标注" }} · 模板
      {{ item.metadata.template || "历史版本"
      }}<template v-if="item.metadata.review_uses_same_model">
        · 同一模型复核</template
      >
    </p>
    <details class="analysis">
      <summary>逐项自动审查意见</summary>
      <p v-if="!item.automatic_review.options" class="help">
        历史题或编辑后题目没有当前自动审查记录，请人工核对。
      </p>
      <div
        v-for="(review, key) in item.automatic_review.options || {}"
        :key="key"
      >
        <h3>
          {{ key }} · {{ review.correct ? "判断为正确选项" : "判断为干扰项" }}
        </h3>
        <p>{{ review.reason }}</p>
        <blockquote v-for="c in review.citations" :key="c.evidence_id">
          {{ c.quote }}
        </blockquote>
      </div>
      <p>{{ item.automatic_review.reason }}</p>
    </details>
    <p v-if="!item.sources_valid" class="notice error">
      原文已删除或引用失效，此题不能审核通过或导出。
    </p>
    <p v-if="item.note" class="help">审核备注：{{ item.note }}</p>
    <div class="review-bar">
      <input
        v-model="notes[item.id]"
        placeholder="审核备注（可选）"
        maxlength="1000"
        aria-label="审核备注"
      /><button class="secondary" :disabled="busy" @click="edit(item)">
        编辑</button
      ><button
        class="secondary danger"
        :disabled="busy"
        @click="review(item, 'rejected')"
      >
        驳回</button
      ><button
        class="primary"
        :disabled="busy || !item.sources_valid"
        @click="review(item, 'approved')"
      >
        审核通过
      </button>
    </div>
    <button class="text-button" @click="history(item)">查看操作记录</button>
    <ul v-if="events[item.id]" class="event-list">
      <li
        v-for="event in events[item.id]"
        :key="event.created_at + event.action"
      >
        {{ new Date(event.created_at).toLocaleString("zh-CN") }} ·
        {{
          {
            generated: "生成待审",
            edited: "编辑重审",
            approved: "审核通过",
            rejected: "驳回",
            source_changed: "来源变化待复核",
          }[event.action]
        }}
        · {{ event.detail }}
      </li>
    </ul>
  </article>
  <div v-if="editing" class="modal-backdrop" @click.self="editing = null">
    <form class="modal stack" @submit.prevent="save">
      <div class="section-title">
        <h2>编辑题目</h2>
        <button type="button" class="text-button" @click="editing = null">
          关闭
        </button>
      </div>
      <label
        >题干<textarea
          v-model="editing.content.topic"
          rows="4"
          required
        ></textarea></label
      ><label v-for="key in 'ABCD'" :key="key"
        >选项 {{ key }}<input v-model="editing.content.options[key]" required
      /></label>
      <fieldset>
        <legend>正确答案</legend>
        <label v-for="key in 'ABCD'" :key="key" class="check-label"
          ><input
            v-if="editing.content.question_type === 'multiple_choice'"
            type="checkbox"
            v-model="editing.content.answer"
            :value="key"
          /><input
            v-else
            type="radio"
            name="edited-answer"
            :checked="editing.content.answer[0] === key"
            @change="editing.content.answer = [key]"
          />{{ key }}</label
        >
      </fieldset>
      <label
        >解析<textarea
          v-model="editing.content.analysis"
          rows="4"
          required
        ></textarea>
      </label>
      <p class="help">原文引用保持不变；保存后回到待审核状态。</p>
      <p v-if="error" class="notice error">{{ error }}</p>
      <button class="primary" :disabled="busy">保存并重新待审</button>
    </form>
  </div>
</template>
