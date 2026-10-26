<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, send } from "../api";
import type { Answer, DocumentInfo, Evidence } from "../types";
import PdfPage from "./PdfPage.vue";
import EvidenceList from "./EvidenceList.vue";
const route = useRoute(),
  router = useRouter(),
  documents = ref<DocumentInfo[]>([]),
  document = ref<DocumentInfo | null>(null),
  selected = ref(""),
  page = ref(1),
  quote = ref(""),
  selection = ref(""),
  query = ref(""),
  answer = ref<Answer | null>(null),
  error = ref(""),
  message = ref(""),
  busy = ref(false),
  size = ref(800),
  overlap = ref(100),
  predecessor = ref(""),
  parser = ref("native"),
  parsers = ref({ docling: false }),
  impact = ref<{
    diff: string[];
    questions: unknown[];
    relation_ids: string[];
    answer_trace_ids?: string[];
  } | null>(null),
  source = ref<HTMLElement | null>(null);
const current = computed(
  () =>
    document.value?.chunks.find((c) => c.id === selected.value) ||
    document.value?.chunks[0],
);
async function load() {
  try {
    documents.value = await api<DocumentInfo[]>("/documents");
    parsers.value = await api("/parsers");
    const id = String(route.params.id || documents.value[0]?.id || "");
    if (!id) return;
    document.value = await api<DocumentInfo>(`/documents/${id}/reader`);
    parser.value = document.value.parser.startsWith("docling")
      ? "docling"
      : "native";
    selected.value = String(
      route.query.chunk || document.value.chunks[0]?.id || "",
    );
    page.value = Number(route.query.page || current.value?.page || 1);
    quote.value = String(route.query.quote || "");
    selection.value = "";
    answer.value = null;
    impact.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "加载失败";
  }
}
function choose(chunk: Evidence) {
  selected.value = chunk.id;
  page.value = chunk.page || 1;
  quote.value = chunk.text;
  router.replace({
    name: "reader",
    params: { id: document.value!.id },
    query: { chunk: chunk.id, page: chunk.page || 1 },
  });
}
function selectedText() {
  const s = window.getSelection();
  if (s?.anchorNode && source.value?.contains(s.anchorNode)) {
    selection.value = s.toString().trim().slice(0, 2000);
    if (selection.value)
      query.value = `请根据选中原文解释：${selection.value.slice(0, 400)}`;
  }
}
async function ask() {
  if (!document.value || !current.value) return;
  busy.value = true;
  error.value = "";
  try {
    answer.value = await send<Answer>("/ask", {
      query: query.value,
      document_id: document.value.id,
      evidence_ids: [current.value.id],
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : "问答失败";
  } finally {
    busy.value = false;
  }
}
async function generate() {
  if (!document.value || !current.value) return;
  busy.value = true;
  try {
    await send("/questions/generate", {
      query: query.value || selection.value || current.value.text.slice(0, 500),
      document_id: document.value.id,
      evidence_ids: [current.value.id],
    });
    message.value = "出题任务已提交，可在智能出题页面查看进度。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "提交失败";
  } finally {
    busy.value = false;
  }
}
async function saveMetadata() {
  if (!document.value) return;
  try {
    document.value = await send<DocumentInfo>(
      `/documents/${document.value.id}/metadata`,
      document.value.metadata,
      "PUT",
    );
    message.value = "出处信息已保存。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "保存失败";
  }
}
async function rechunk() {
  if (
    !document.value ||
    !window.confirm("重新分块可能使现有引用失效，是否继续？")
  )
    return;
  try {
    await send(`/documents/${document.value.id}/rechunk`, {
      size: size.value,
      overlap: overlap.value,
    });
    await load();
    message.value = "片段已重建，请核对受影响的题目与关系。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "分块失败";
  }
}
async function compare() {
  try {
    if (document.value && predecessor.value)
      impact.value = await api(
        `/documents/${predecessor.value}/impact/${document.value.id}`,
      );
  } catch (e) {
    error.value = e instanceof Error ? e.message : "比较失败";
  }
}
async function reparse() {
  if (
    !document.value ||
    !window.confirm("重新解析会重建片段，现有引用可能失效，是否继续？")
  )
    return;
  busy.value = true;
  try {
    await send(`/documents/${document.value.id}/reparse`, {
      parser: parser.value,
    });
    await load();
    message.value = "重新解析完成，请核对原文定位与旧引用。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "解析失败";
  } finally {
    busy.value = false;
  }
}
async function link() {
  if (
    !document.value ||
    !window.confirm("确认后旧版退出默认检索，受影响题目会退回待审，是否继续？")
  )
    return;
  try {
    await send(`/documents/${document.value.id}/version`, {
      predecessor: predecessor.value,
    });
    await load();
    message.value = "版本链已更新；旧资料仍可追溯。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "关联失败";
  }
}
onMounted(load);
watch(() => route.params.id, load);
watch(
  () => route.query.chunk,
  () => {
    selected.value = String(route.query.chunk || selected.value);
    page.value = Number(route.query.page || current.value?.page || 1);
    quote.value = String(route.query.quote || current.value?.text || "");
  },
);
</script>
<template>
  <details class="panel">
    <summary>重新解析原始资料</summary>
    <label
      >解析器<select aria-label="解析器" v-model="parser">
        <option value="native">轻量解析</option>
        <option value="docling" :disabled="!parsers.docling">
          Docling{{ parsers.docling ? "" : "（未安装）" }}
        </option>
      </select></label
    ><button class="secondary" :disabled="busy || !document" @click="reparse">
      重新解析
    </button>
  </details>
  <section class="page-intro">
    <div>
      <p class="eyebrow">READ · VERIFY · LEARN</p>
      <h1>资料阅读与证据定位</h1>
      <p>选中原文解释或出题，引用直接回到页码与片段。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="message" class="notice success">{{ message }}</p>
  <select
    :value="document?.id"
    aria-label="阅读资料"
    @change="
      router.push({
        name: 'reader',
        params: { id: ($event.target as HTMLSelectElement).value },
      })
    "
  >
    <option v-for="item in documents" :key="item.id" :value="item.id">
      {{ item.title }}{{ item.active ? "" : "（旧版）" }}
    </option>
  </select>
  <div v-if="!document" class="panel empty section-gap">请先导入资料。</div>
  <template v-else
    ><p v-if="!document.active" class="notice">
      这是已被替代的历史版本，不参与默认检索。
    </p>
    <div class="reader-layout section-gap">
      <section ref="source" class="panel source-pane" @mouseup="selectedText">
        <div class="section-title">
          <h2>{{ document.title }}</h2>
          <span class="tag">{{ document.parser }}</span>
        </div>
        <div v-if="document.kind === 'pdf'" class="inline">
          <label
            >页码<input
              v-model.number="page"
              type="number"
              min="1"
              :max="document.pages" /></label
          ><span class="muted">共 {{ document.pages }} 页</span>
        </div>
        <PdfPage
          v-if="document.kind === 'pdf'"
          :document-id="document.id"
          :page="page"
          :quote="quote"
        />
        <div class="chunk-tabs">
          <button
            v-for="chunk in document.chunks"
            :key="chunk.id"
            :class="['secondary', { selected: current?.id === chunk.id }]"
            @click="choose(chunk)"
          >
            {{ chunk.heading || chunk.location }}
          </button>
        </div>
        <article v-if="current" class="reader-text">
          <h3>{{ current.location }}</h3>
          <pre v-if="current.kind === 'table'">{{ current.text }}</pre>
          <p v-else>
            <template v-if="quote && current.text.includes(quote)"
              >{{ current.text.slice(0, current.text.indexOf(quote))
              }}<mark>{{ quote }}</mark
              >{{
                current.text.slice(current.text.indexOf(quote) + quote.length)
              }}</template
            ><template v-else>{{ current.text }}</template>
          </p>
        </article>
      </section>
      <aside class="panel stack">
        <h2>围绕当前原文学习</h2>
        <blockquote v-if="selection">{{ selection }}</blockquote>
        <textarea
          v-model="query"
          rows="4"
          placeholder="输入问题，或在左侧选中一段文字"
        ></textarea>
        <div class="inline">
          <button
            class="primary"
            :disabled="busy || !query.trim() || !document.active"
            @click="ask"
          >
            依据当前片段回答</button
          ><button
            class="secondary"
            :disabled="busy || !document.active"
            @click="generate"
          >
            基于原文出题
          </button>
        </div>
        <div v-for="block in answer?.blocks || []" :key="block.text">
          <p>{{ block.text }}</p>
          <blockquote v-for="c in block.citations" :key="c.evidence_id">
            {{ c.quote }}
          </blockquote>
        </div>
        <p v-if="answer?.status === 'insufficient_evidence'" class="notice">
          当前片段没有足够依据。
        </p>
        <EvidenceList v-if="answer" :items="answer.evidence" />
        <details>
          <summary>资料出处与版本</summary>
          <div class="stack">
            <label>发布来源<input v-model="document.metadata.source" /></label
            ><label>版本<input v-model="document.metadata.edition" /></label
            ><label
              >年份<input
                type="number"
                :value="document.metadata.year || ''"
                @input="
                  document.metadata.year = ($event.target as HTMLInputElement)
                    .value
                    ? Number(($event.target as HTMLInputElement).value)
                    : null
                " /></label
            ><label>适用范围<input v-model="document.metadata.scope" /></label
            ><label>章节<input v-model="document.metadata.chapter" /></label
            ><button class="secondary" @click="saveMetadata">保存出处</button
            ><label
              >此资料替代哪个旧版<select
                aria-label="此资料替代哪个旧版"
                v-model="predecessor"
              >
                <option value="">选择旧版</option>
                <option
                  v-for="item in documents.filter((d) => d.id !== document?.id)"
                  :key="item.id"
                  :value="item.id"
                >
                  {{ item.title }}
                </option>
              </select></label
            ><button
              class="secondary"
              :disabled="!predecessor"
              @click="compare"
            >
              比较版本影响
            </button>
            <div v-if="impact">
              <p>
                影响 {{ impact.questions.length }} 道题、{{
                  impact.relation_ids.length
                }}
                条关系
              </p>
              <pre class="diff">{{ impact.diff.join("\n") }}</pre>
              <button class="primary" @click="link">确认关联为新版本</button>
            </div>
          </div>
        </details>
        <details>
          <summary>人工调整分块</summary>
          <div class="inline">
            <label
              >片段字数<input
                type="number"
                v-model.number="size"
                min="200"
                max="2000" /></label
            ><label
              >重叠字数<input
                type="number"
                v-model.number="overlap"
                min="0"
                max="150"
            /></label>
          </div>
          <button class="secondary" @click="rechunk">重新分块</button>
          <p class="help">
            只从原始资料重新切分，不允许将无来源的新文字写成原文。
          </p>
        </details>
      </aside>
    </div></template
  >
</template>
