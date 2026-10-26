<script setup>
import { onMounted, ref } from "vue";
import { api, send } from "../api";
const form = ref(null),
  key = ref(null),
  status = ref(null),
  index = ref(null),
  error = ref(""),
  message = ref(""),
  busy = ref(false);
const emit = defineEmits(["changed"]);
async function testReview() {
  await save(false);
  if (error.value) return;
  busy.value = true;
  try {
    message.value = (await send("/settings/test-review", {})).message;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function load() {
  [form.value, status.value, index.value] = await Promise.all([
    api("/settings"),
    api("/status"),
    api("/indexes/status"),
  ]);
}
async function save(test = false) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    const {
      cloud_api_key_configured,
      cloud_api_key_from_environment,
      ...value
    } = form.value;
    form.value = await send(
      "/settings",
      { ...value, cloud_api_key: key.value },
      "PUT",
    );
    key.value = null;
    emit("changed");
    message.value = test
      ? (await send("/settings/test", {})).message
      : "设置已保存，后续生成将使用当前配置。";
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function build() {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await send("/indexes/build", {});
    index.value = await api("/indexes/status");
    message.value = "向量索引已建立。";
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(() => load().catch((e) => (error.value = e.message)));
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">YOUR MODELS, YOUR CHOICE</p>
      <h1>选择适合你的模型</h1>
      <p>本地与云端共用一套工作流程，在这里切换后即可使用。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="message" class="notice success" role="status">{{ message }}</p>
  <form v-if="form" class="settings-layout" @submit.prevent="save(false)">
    <section class="panel stack">
      <h2>生成模型</h2>
      <div
        v-if="form.review_provider === 'cloud' && form.provider !== 'cloud'"
        class="stack"
      >
        <label
          >审题云端接口地址<input
            v-model="form.cloud_base_url"
            type="url"
            placeholder="https://服务商地址/v1" /></label
        ><label>云端默认模型<input v-model="form.cloud_model" /></label
        ><label
          >审题云端密钥<input
            type="password"
            :value="key || ''"
            @input="key = $event.target.value"
            placeholder="留空保持已存储密钥"
            autocomplete="new-password"
        /></label>
      </div>
      <label
        v-if="form.review_provider === 'ollama' && form.provider !== 'ollama'"
        >审题本地服务地址<input v-model="form.ollama_base_url" type="url"
      /></label>
      <button
        type="button"
        class="secondary"
        :disabled="busy"
        @click="testReview"
      >
        保存并检查审题连接
      </button>
      <label
        >审题模型来源<select
          aria-label="审题模型来源"
          v-model="form.review_provider"
        >
          <option value="same">与生成模型相同</option>
          <option value="ollama">本地 Ollama</option>
          <option value="cloud">云端模型</option>
        </select></label
      >
      <label v-if="form.review_provider !== 'same'"
        >审题模型名称<input
          v-model="form.review_model"
          placeholder="留空使用所选来源的默认模型"
      /></label>
      <p class="help">
        审题可独立选择模型；服务地址与密钥使用下方对应来源的设置。同一模型复核会在题目记录中注明。
      </p>
      <fieldset class="provider-choice">
        <legend class="sr-only">模型提供方式</legend>
        <label :class="{ chosen: form.provider === 'ollama' }"
          ><input type="radio" v-model="form.provider" value="ollama" /><strong
            >本地 Ollama</strong
          ><small>使用本机已下载的模型</small></label
        ><label :class="{ chosen: form.provider === 'cloud' }"
          ><input type="radio" v-model="form.provider" value="cloud" /><strong
            >云端模型</strong
          ><small>使用兼容的云端接口</small></label
        >
      </fieldset>
      <template v-if="form.provider === 'ollama'"
        ><label
          >服务地址<input
            v-model="form.ollama_base_url"
            type="url"
            placeholder="http://127.0.0.1:11434"
            required /></label
        ><label
          >模型名称<input
            v-model="form.ollama_model"
            placeholder="qwen2.5"
            required /></label></template
      ><template v-else
        ><label
          >接口地址<input
            v-model="form.cloud_base_url"
            type="url"
            placeholder="https://服务商地址/v1"
            required /></label
        ><label
          >模型名称<input
            v-model="form.cloud_model"
            placeholder="填写服务商提供的模型 ID"
            required /></label
        ><label
          >API 密钥<input
            type="password"
            :value="key || ''"
            @input="key = $event.target.value"
            :placeholder="
              form.cloud_api_key_configured
                ? '已配置；留空保持原密钥'
                : '填写 API 密钥'
            "
            autocomplete="new-password"
        /></label>
        <p class="help">
          {{
            form.cloud_api_key_from_environment
              ? "密钥由本机环境变量提供。"
              : "密钥保存在本机，读取设置时不会返回明文。"
          }}
        </p>
        <button
          v-if="
            form.cloud_api_key_configured &&
            !form.cloud_api_key_from_environment
          "
          type="button"
          class="text-button danger"
          @click="
            key = '';
            message = '保存设置后将清除已存储的密钥。';
          "
        >
          清除已保存密钥
        </button>
        <p class="help">
          云端服务需支持 OpenAI-compatible Chat Completions 与 JSON
          输出。请求会发送检索到的资料片段，调用费用由服务商计收。
        </p></template
      ><label
        >生成超时（秒）<input
          type="number"
          v-model.number="form.request_timeout"
          min="10"
          max="600"
      /></label>
      <div class="inline">
        <button class="primary" :disabled="busy">保存设置</button
        ><button
          class="secondary"
          type="button"
          :disabled="busy"
          @click="save(true)"
        >
          {{ busy ? "处理中…" : "保存并测试连接" }}
        </button>
      </div>
    </section>
    <section class="panel stack">
      <h2>检索设置</h2>
      <label
        >最多引用的片段数<input
          type="number"
          v-model.number="form.top_k"
          min="1"
          max="10" /></label
      ><label class="check-label"
        ><input type="checkbox" v-model="form.use_vectors" />启用 BGE
        向量检索</label
      >
      <p class="help">
        模型文件{{ status?.embedding_ready ? "已就绪" : "尚未下载完整" }} ·
        {{ index?.message }}
      </p>
      <label class="check-label"
        ><input type="checkbox" v-model="form.use_reranker" />启用 BGE
        重排序</label
      >
      <p class="help">
        重排模型{{
          status?.reranker_ready ? "已就绪" : "尚未下载完整"
        }}。不可用时保留关键词检索结果，并显示提示。
      </p>
      <label
        >检索模型运行设备<select
          aria-label="检索模型运行设备"
          v-model="form.device"
        >
          <option value="cpu">CPU（为生成模型保留显存）</option>
          <option value="cuda">NVIDIA GPU</option>
        </select></label
      ><button
        class="secondary"
        type="button"
        :disabled="busy || !status?.embedding_ready"
        @click="build"
      >
        {{ busy ? "处理中…" : "重建向量索引" }}
      </button>
      <p class="help">
        先保存检索设置，再重建索引。资料发生变化后需重建；关键词检索始终可以独立使用。
      </p>
      <div class="notice">
        <strong>Neo4j 图谱</strong>
        <p>
          {{
            status?.neo4j_configured
              ? "已提供连接配置，可在图谱页面尝试查询。"
              : "尚未配置，当前使用资料中的概念共现图。"
          }}
        </p>
        <small>连接信息请在本机 .env 配置，说明见项目文档。</small>
      </div>
    </section>
  </form>
</template>
