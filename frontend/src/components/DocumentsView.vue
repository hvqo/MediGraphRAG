<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api";
import { useRouter } from "vue-router";
const router = useRouter();
import EvidenceList from "./EvidenceList.vue";
const items = ref([]),
  title = ref(""),
  text = ref(""),
  error = ref(""),
  message = ref(""),
  busy = ref(false),
  preview = ref(null);
const emit = defineEmits(["changed"]);
async function load() {
  items.value = await api("/documents");
}
async function upload(event) {
  const list = Array.from(event.target.files || []);
  if (!list.length) return;
  busy.value = true;
  error.value = "";
  try {
    const form = new FormData();
    for (const file of list) form.append("files", file);
    form.append("instruction", "提炼这些资料的知识点");
    const task = await api("/workspace/submit", { method: "POST", body: form });
    router.push({ name: "ask", query: { task: task.id } });
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
    event.target.value = "";
  }
}
async function paste() {
  busy.value = true;
  error.value = "";
  try {
    const form = new FormData();
    form.append(
      "files",
      new File([text.value], (title.value.trim() || "粘贴资料") + ".txt", {
        type: "text/plain",
      }),
    );
    form.append("instruction", "提炼这些资料的知识点");
    const task = await api("/workspace/submit", { method: "POST", body: form });
    title.value = "";
    text.value = "";
    router.push({ name: "ask", query: { task: task.id } });
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function remove(item) {
  if (
    !window.confirm(
      `删除“${item.title}”？相关题目会保留，但失去原文依据后不能审核通过或导出。`,
    )
  )
    return;
  try {
    await api("/documents/" + item.id, { method: "DELETE" });
    preview.value = null;
    await load();
    emit("changed");
  } catch (e) {
    error.value = e.message;
  }
}
async function inspect(item) {
  try {
    const detail = await api("/documents/" + item.id);
    preview.value = {
      ...detail,
      chunks: detail.chunks.map((c) => ({
        ...c,
        title: detail.title,
        filename: detail.filename,
      })),
    };
  } catch (e) {
    error.value = e.message;
  }
}
onMounted(() => load().catch((e) => (error.value = e.message)));
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">YOUR MEDICAL LIBRARY</p>
      <h1>让知识有据可查</h1>
      <p>导入医学资料，保留原文位置，为问答和出题建立共同的依据。</p>
    </div>
    <span class="pill">{{ items.length }} 份资料</span>
  </section>
  <p v-if="error" role="alert" class="notice error">{{ error }}</p>
  <p v-if="message" class="notice success" role="status">{{ message }}</p>
  <div class="two-columns">
    <section class="panel">
      <h2>导入文件</h2>
      <label class="upload-zone" :class="{ loading: busy }"
        ><span class="upload-icon">↑</span
        ><strong>{{ busy ? "正在解析资料…" : "选择医学资料文件" }}</strong
        ><span>图片、PDF、Word、TXT、Markdown · 可批量选择 · 每份最大25MB</span
        ><input
          type="file"
          multiple
          accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.txt,.md,.markdown"
          :disabled="busy"
          @change="upload"
      /></label>
      <p class="help">
        PDF 保留页码，Word
        和文本保留段落。图片和扫描PDF会自动尝试视觉识别，后台继续整理资料。
      </p>
    </section>
    <form class="panel stack" @submit.prevent="paste">
      <h2>粘贴文本</h2>
      <label
        >资料名称<input
          v-model="title"
          placeholder="例如：内科学 · 呼吸系统学习笔记"
          maxlength="200"
          required /></label
      ><label
        >原文内容<textarea
          v-model="text"
          rows="4"
          placeholder="粘贴需要作为依据的医学资料正文…"
          required
        ></textarea></label
      ><button
        class="primary"
        :disabled="busy || !title.trim() || !text.trim()"
      >
        导入文本
      </button>
    </form>
  </div>
  <section class="panel section-gap">
    <div class="section-title">
      <h2>资料库</h2>
      <span class="muted">原文件和片段保存在本机</span>
    </div>
    <div v-if="!items.length" class="empty">
      <span class="empty-mark">＋</span>
      <h3>从第一份资料开始</h3>
      <p>导入教材、指南或学习笔记后，就可以检索原文了。</p>
    </div>
    <div v-else class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>资料名称</th>
            <th>格式</th>
            <th>内容</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <strong>{{ item.title }}</strong
              ><small>{{ item.filename }}</small
              ><small
                v-for="warning in item.warnings"
                :key="warning"
                class="warning-text"
                >{{ warning }}</small
              >
            </td>
            <td>
              <span class="tag">{{ item.kind.toUpperCase() }}</span>
            </td>
            <td>
              {{ item.chunk_count }} 个片段<span v-if="item.pages">
                · {{ item.pages }} 页</span
              >
            </td>
            <td>
              <div class="inline">
                <button
                  class="text-button"
                  @click="
                    router.push({ name: 'reader', params: { id: item.id } })
                  "
                >
                  打开阅读器</button
                ><button class="text-button" @click="inspect(item)">
                  查看原文</button
                ><button class="text-button danger" @click="remove(item)">
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <section v-if="preview" class="panel section-gap">
    <div class="section-title">
      <h2>{{ preview.title }} · 原文片段</h2>
      <button class="text-button" @click="preview = null">收起</button>
    </div>
    <EvidenceList :items="preview.chunks" />
  </section>
</template>
