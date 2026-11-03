<script setup>
import { ref, onActivated, onDeactivated, onBeforeUnmount, watch } from "vue";
import { api, send, API } from "../api";
import { useRoute } from "vue-router";
import EvidenceList from "./EvidenceList.vue";
import { useWorkspace } from "../stores/workspace";
const workspace = useWorkspace(),
  route = useRoute();
const query = ref(""),
  result = ref(null),
  answer = ref(null),
  busy = ref(false),
  error = ref(""),
  selected = ref(""),
  files = ref([]),
  picker = ref(null),
  operation = ref(null),
  questions = ref([]),
  recent = ref([]);
let timer = null;
function attach(list) {
  files.value = [...files.value, ...Array.from(list || [])].slice(0, 100);
}
function pasted(event) {
  if (event.clipboardData?.files.length) {
    attach(event.clipboardData.files);
    event.preventDefault();
  }
}
async function inspect(id) {
  questions.value = [];
  answer.value = null;
  operation.value = await api("/workspace/operations/" + id);
  await refreshOperation();
  start();
}
async function refreshOperation() {
  if (!operation.value) return;
  const row = await api("/workspace/operations/" + operation.value.id);
  operation.value = row;
  busy.value = ["queued", "running"].includes(row.status);
  if (row.result.answer) answer.value = row.result.answer;
  if (row.result.question_ids?.length && !questions.value.length)
    questions.value = await Promise.all(
      row.result.question_ids.map((id) => api("/questions/" + id)),
    );
  if (["completed", "failed"].includes(row.status)) stop();
  await workspace.refresh();
}
function stop() {
  clearInterval(timer);
  timer = null;
}
function start() {
  stop();
  timer = setInterval(
    () =>
      refreshOperation().catch((e) => {
        error.value = e.message;
        stop();
        busy.value = false;
      }),
    1500,
  );
}
async function quick(text) {
  query.value = text;
  await run();
}
async function run() {
  busy.value = true;
  error.value = "";
  answer.value = null;
  questions.value = [];
  result.value = null;
  try {
    if (files.value.length) {
      const form = new FormData();
      for (const file of files.value) form.append("files", file);
      form.append("instruction", query.value);
      operation.value = await api("/workspace/submit", {
        method: "POST",
        body: form,
      });
      files.value = [];
      start();
    } else if (
      /出题|出\s*[一二三四五六七八九十两0-9]+\s*(?:道|个)?(?:单选|多选|选择|判断)?题|生成.{0,12}(?:题|试卷)|试题|练习题|考题|试卷|知识点|总结|提炼|摘要|整理|generate.*question|quiz|summari/i.test(
        query.value,
      )
    ) {
      operation.value = await send("/workspace/request", {
        instruction: query.value,
        document_ids: /全部资料|整个资料库|所有资料|全库/.test(query.value)
          ? []
          : operation.value?.result?.document_ids || [],
      });
      start();
    } else {
      stop();
      answer.value = await send("/ask", {
        query: query.value,
        document_ids: /全部资料|整个资料库|所有资料|全库/.test(query.value)
          ? []
          : operation.value?.result?.document_ids || [],
      });
      result.value = answer.value.retrieval;
      busy.value = false;
    }
  } catch (e) {
    error.value = e.message;
    busy.value = false;
  }
}
async function approve(question) {
  try {
    const updated = await send("/questions/" + question.id + "/review", {
      status: "approved",
      note: "在上传任务结果中核对通过",
    });
    Object.assign(question, updated);
  } catch (e) {
    error.value = e.message;
  }
}
onActivated(async () => {
  try {
    recent.value = await api("/workspace/operations");
    if (route.query.task) await inspect(String(route.query.task));
    else if (
      operation.value &&
      !["completed", "failed"].includes(operation.value.status)
    )
      start();
  } catch (e) {
    error.value = e.message;
  }
});
watch(
  () => route.query.task,
  (id) => {
    if (id && id !== operation.value?.id)
      inspect(String(id)).catch((e) => (error.value = e.message));
  },
);
onDeactivated(stop);
onBeforeUnmount(stop);
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
  <form class="question-bar" @submit.prevent="run" @paste="pasted">
    <label class="sr-only" for="medical-query">医学问题</label
    ><input
      id="medical-query"
      v-model="query"
      placeholder="直接提问，或上传资料后说：根据这些内容生成3道题"
      maxlength="1000"
    /><button
      class="primary"
      :disabled="busy || (!query.trim() && !files.length)"
    >
      {{ busy ? "正在处理…" : files.length ? "开始处理 →" : "依据问答 →" }}
    </button>
  </form>
  <p v-if="!workspace.summary.documents" class="notice">
    还没有资料。<RouterLink :to="{ name: 'documents' }"
      >添加第一份资料</RouterLink
    >，之后输入问题即可；系统自动选择检索路径。
  </p>
  <section
    class="upload-composer"
    @dragover.prevent
    @drop.prevent="attach($event.dataTransfer.files)"
  >
    <input
      ref="picker"
      type="file"
      multiple
      accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md"
      class="sr-only"
      aria-label="添加资料文件"
      @change="
        attach($event.target.files);
        $event.target.value = '';
      "
    /><button class="secondary" :disabled="busy" @click="picker.click()">
      ＋ 添加图片或文档</button
    ><span class="help"
      >也可以拖入一批文件，或粘贴截图。会自动存入你的个人资料库。</span
    >
    <div class="inline">
      <span v-for="(file, i) in files" :key="i" class="tag"
        >{{ file.name
        }}<button
          class="text-button"
          @click="files.splice(i, 1)"
          :aria-label="'移除' + file.name"
        >
          ×
        </button></span
      >
    </div>
    <div class="inline section-gap">
      <button
        class="secondary"
        :disabled="busy || (!files.length && !workspace.summary.documents)"
        @click="quick('提炼这些资料的知识点')"
      >
        提炼知识点</button
      ><button
        class="secondary"
        :disabled="busy || (!files.length && !workspace.summary.documents)"
        @click="quick('根据这些资料生成3道练习题')"
      >
        生成3道练习题
      </button>
    </div>
  </section>
  <section v-if="operation" class="panel stack section-gap">
    <h2>{{ operation.progress.stage }}</h2>
    <p>
      {{ operation.progress.processed }} /
      {{ operation.progress.total }} 份文件已读取 · 原文件已自动保存
    </p>
    <p v-if="operation.error" class="notice error">
      {{ operation.error
      }}<button
        class="text-button"
        @click="
          send('/workspace/operations/' + operation.id + '/retry', {}).then(
            inspect.bind(null, operation.id),
          )
        "
      >
        重试请求
      </button>
    </p>
    <p
      v-for="file in operation.result.files || []"
      :key="file.filename"
      class="help"
    >
      {{ file.filename }} · {{ file.status === "ready" ? "可用" : file.error }}
    </p>
    <article v-for="point in operation.result.points || []" :key="point.title">
      <h3>{{ point.title }}</h3>
      <p>{{ point.text }}</p>
      <blockquote
        v-for="citation in point.citations"
        :key="citation.evidence_id"
      >
        {{ citation.quote }}
      </blockquote>
    </article>
    <p v-if="operation.result.background" class="notice success">
      你的资料已保存。{{
        operation.status === "completed"
          ? operation.result.background.vectors === "ready"
            ? "索引与关系已整理完成，可继续问答或出题。"
            : "资料和关系已保存，向量索引尚不可用，提问时会自动使用关键词检索。"
          : "正在后台补充检索索引与资料关联，不必等待，也不需要手动建库。"
      }}
    </p>
    <details v-if="operation.result.background">
      <summary>查看整理进度</summary>
      <p>
        向量：{{ operation.result.background.vectors }} · 关系：{{
          operation.result.background.graph
        }}
      </p>
      <p>{{ operation.result.coverage?.note }}</p>
    </details>
    <p v-if="operation.result.question_error" class="notice error">
      {{ operation.result.question_error }}
    </p>
  </section>
  <div
    v-if="operation?.result.request_status === 'completed'"
    class="inline section-gap"
  >
    <span class="help">这些资料还可以：</span>
    <button
      class="text-button"
      :disabled="busy"
      @click="quick('提炼这些资料的知识点')"
    >
      提炼知识点
    </button>
    <button
      class="text-button"
      :disabled="busy"
      @click="quick('根据这些资料生成3道练习题')"
    >
      生成练习题
    </button>
    <RouterLink
      v-if="operation.result.document_ids?.length"
      :to="{ name: 'reader', params: { id: operation.result.document_ids[0] } }"
      >打开原文核对</RouterLink
    >
    <RouterLink :to="{ name: 'study' }">开始复习</RouterLink>
  </div>
  <section v-if="questions.length" class="panel stack section-gap">
    <h2>已根据资料生成 {{ questions.length }} 道题</h2>
    <article v-for="question in questions" :key="question.id" class="chunk">
      <h3>{{ question.content.topic }}</h3>
      <p v-for="(option, key) in question.content.options" :key="key">
        {{ key }}. {{ option }}
      </p>
      <details>
        <summary>核对答案、解析与原文</summary>
        <p>答案：{{ question.content.answer.join("、") }}</p>
        <p>{{ question.content.analysis }}</p>
        <EvidenceList :items="question.evidence" />
      </details>
      <button
        class="secondary"
        :disabled="question.status === 'approved' || !question.sources_valid"
        @click="approve(question)"
      >
        {{
          question.status === "approved"
            ? "已通过，可在练习中使用"
            : "核对通过，加入练习"
        }}
      </button>
    </article>
  </section>
  <details v-if="recent.length && !operation" class="section-gap">
    <summary>继续上次的资料任务</summary>
    <button
      v-for="item in recent.slice(0, 5)"
      :key="item.id"
      class="text-button"
      @click="inspect(item.id)"
    >
      {{ item.instruction || "资料整理" }} · {{ item.progress.stage }}
    </button>
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
  <div v-if="!operation || answer || result" class="answer-layout section-gap">
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
              : "直接提问，或在这里添加资料后说明你想做什么。"
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
