<script setup>
import { ref } from "vue";
import { send } from "../api";
import EvidenceList from "./EvidenceList.vue";
import { useWorkspace } from "../stores/workspace";
const workspace = useWorkspace();
const query = ref(""),
  mode = ref("auto"),
  result = ref(null),
  answer = ref(null),
  busy = ref(false),
  error = ref(""),
  selected = ref("");
async function run(generate) {
  busy.value = true;
  error.value = "";
  answer.value = null;
  try {
    if (generate) {
      answer.value = await send("/ask", {
        query: query.value,
        mode: mode.value,
      });
      result.value = answer.value.retrieval;
    } else
      result.value = await send("/search", {
        query: query.value,
        mode: mode.value,
      });
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">EVIDENCE BEFORE ANSWERS</p>
      <h1>从原文出发，理解医学知识</h1>
      <p>检索已导入的医学资料，让回答的每一段都能回到出处。</p>
    </div>
    <span class="pill">医学学习与研究</span>
  </section>
  <form class="question-bar" @submit.prevent="run(true)">
    <label class="sr-only" for="medical-query">医学问题</label
    ><input
      id="medical-query"
      v-model="query"
      placeholder="输入医学概念、知识点或学习问题…"
      maxlength="1000"
      required
    /><button class="primary" :disabled="busy || !query.trim()">
      {{ busy ? "正在处理…" : "依据问答 →" }}
    </button>
  </form>
  <p v-if="!workspace.summary.documents" class="notice">
    还没有资料。<RouterLink :to="{ name: 'documents' }"
      >添加第一份资料</RouterLink
    >，之后输入问题即可；系统自动选择检索路径。
  </p>
  <details class="query-options section-gap">
    <summary>检索选项与原文搜索</summary>
    <div class="inline">
      <label
        >检索方式<select v-model="mode" aria-label="检索方式">
          <option value="auto">自动判断（推荐）</option>
          <option value="keyword">仅关键词</option>
          <option value="vector">仅向量</option>
          <option value="graph">仅审核关系</option>
          <option value="hybrid">固定融合</option>
        </select></label
      ><button
        type="button"
        class="secondary"
        :disabled="busy || !query.trim()"
        @click="run(false)"
      >
        只查原文
      </button>
    </div>
    <p class="help">
      普通查询先快速检索；关系或比较问题尝试补充已审核路径。没有可用图谱时保留文本依据。
    </p>
  </details>
  <div v-if="result?.routing" class="help">
    {{
      result.routing.selected === "deep" ? "已补充关系依据" : "已使用快速检索"
    }}
    <details>
      <summary>查看检索依据</summary>
      {{ result.routing.reason }}
      <p>本次检索 {{ result.elapsed_ms }} 毫秒，不含生成与审题耗时。</p>
      <p v-if="result.routing.fallback">{{ result.routing.fallback }}</p>
    </details>
  </div>
  <p v-if="error" role="alert" class="notice error">{{ error }}</p>
  <div class="answer-layout section-gap">
    <section class="panel answer-panel">
      <div class="section-title">
        <h2>知识解答</h2>
        <span v-if="answer?.status === 'draft'" class="tag amber"
          >生成内容，请核对原文</span
        >
      </div>
      <div v-if="busy" class="empty" role="status">
        <span class="spinner"></span>
        <h3>正在检索和核验依据</h3>
        <p>本地模型首次加载可能需要一些时间。</p>
      </div>
      <div v-else-if="answer?.blocks?.length" class="answer-body">
        <div v-for="(block, index) in answer.blocks" :key="index">
          <p>{{ block.text }}</p>
          <button
            v-for="citation in block.citations"
            :key="citation.evidence_id"
            class="citation"
            @click="selected = citation.evidence_id"
          >
            原文依据 · {{ citation.quote.slice(0, 24)
            }}{{ citation.quote.length > 24 ? "…" : "" }}
          </button>
        </div>
      </div>
      <div v-else-if="answer?.status === 'insufficient_evidence'" class="empty">
        <h3>目前没有足够依据</h3>
        <p>可以补充相关资料，或把问题缩小到具体考点。</p>
      </div>
      <div v-else class="empty">
        <span class="empty-mark">✧</span>
        <h3>
          {{ result ? "相关原文已列在依据区" : "好的答案，从可靠资料开始" }}
        </h3>
        <p>
          {{
            result
              ? "选择“依据问答”，由模型整理回答并核验引用。"
              : "先在资料库中导入内容，再输入问题。也可以只检索原文。"
          }}
        </p>
      </div>
      <p class="footnote">
        自动引用校验不等同于医学正确性证明；学习时请结合原始资料核对。
      </p>
    </section>
    <aside class="panel">
      <div class="section-title">
        <h2>原文依据</h2>
        <span class="tag"
          >{{ (answer?.evidence || result?.items || []).length }} 条</span
        >
      </div>
      <p v-if="result" class="help">
        检索方式：{{
          result.mode
            .split("+")
            .map(
              (part) =>
                ({
                  keyword: "关键词",
                  cooccurrence: "概念共现",
                  vector: "语义向量",
                  reranker: "重排序",
                  reviewed_relations: "已审核关系",
                })[part] || part,
            )
            .join(" · ")
        }}
      </p>
      <p
        v-for="warning in result?.warnings || []"
        :key="warning"
        class="notice"
      >
        {{ warning }}
      </p>
      <EvidenceList
        :items="answer?.evidence || result?.items || []"
        :selected="selected"
      />
    </aside>
  </div>
</template>
