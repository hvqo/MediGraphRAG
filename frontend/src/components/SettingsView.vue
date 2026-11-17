<script setup>
import { onMounted, ref } from "vue";
import { api, send } from "../api";
const form = ref(null),
  key = ref(null),
  visionKey = ref(null),
  reviewKey = ref(null),
  status = ref(null),
  index = ref(null),
  error = ref(""),
  message = ref(""),
  busy = ref(false);
const emit = defineEmits(["changed"]);
async function testVision() {
  await save(false);
  if (error.value) return;
  busy.value = true;
  try {
    const result = await send("/settings/test-vision", {});
    if (!result.ok) error.value = result.message;
    else message.value = result.message;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function testReview() {
  await save(false);
  if (error.value) return;
  busy.value = true;
  try {
    const result = await send("/settings/test-review", {});
    if (!result.ok) {
      error.value = result.message;
      message.value = "";
    } else message.value = result.message;
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
    const value = Object.fromEntries(
      Object.entries(form.value).filter(
        ([field]) =>
          !field.endsWith("_configured") &&
          !field.endsWith("_from_environment"),
      ),
    );
    form.value = await send(
      "/settings",
      {
        ...value,
        cloud_api_key: key.value,
        vision_api_key: visionKey.value,
        review_api_key: reviewKey.value,
      },
      "PUT",
    );
    key.value = null;
    visionKey.value = null;
    reviewKey.value = null;
    emit("changed");
    if (test) {
      const result = await send("/settings/test", {});
      if (!result.ok) error.value = result.message;
      else message.value = result.message;
    } else message.value = "设置已保存，后续生成将使用当前配置。";
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
          <option value="openai">本地兼容服务（llama.cpp / LM Studio）</option>
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
      <template v-if="form.review_provider !== 'same'">
        <label
          >独立审题服务地址（可选）<input
            v-model="form.review_base_url"
            type="url"
            placeholder="留空沿用生成模型对应来源的地址"
        /></label>
        <label
          v-if="
            form.review_provider === 'cloud' ||
            form.review_provider === 'openai'
          "
          >独立审题密钥（可选）<input
            type="password"
            :value="reviewKey || ''"
            @input="reviewKey = $event.target.value"
            :placeholder="
              form.review_api_key_configured
                ? '已配置；留空保留'
                : '未配置时沿用文字云端密钥'
            "
            autocomplete="new-password"
        /></label>
        <button
          v-if="
            form.review_api_key_configured &&
            !form.review_api_key_from_environment
          "
          type="button"
          class="text-button danger"
          @click="reviewKey = ''"
        >
          清除独立审题密钥（保存后生效）
        </button>
      </template>
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
        <label :class="{ chosen: form.provider === 'openai' }"
          ><input
            type="radio"
            v-model="form.provider"
            value="openai"
            @change="
              form.cloud_base_url ||= 'http://127.0.0.1:8081/v1';
              form.cloud_model ||= 'qwen3-vl:8b-instruct';
            "
          /><strong>本地兼容服务</strong
          ><small>llama.cpp / LM Studio，无需云端密钥</small></label
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
          {{
            form.provider === "openai"
              ? "本地服务需支持 /v1/chat/completions、图片及JSON输出。未开启认证时密钥可以留空。llama.cpp默认端口8081，LM Studio常用1234。"
              : "云端服务需支持OpenAI-compatible Chat Completions与JSON输出。请求会发送检索到的资料片段，调用费用由服务商计收。"
          }}
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
      <h2>图片与文档理解</h2>
      <p class="help">
        普通文字优先直接读取，清晰文字图片优先OCR；图示或识别不确定时才使用视觉模型。用户提问时无需选择。
      </p>
      <label
        >视觉模型来源<select
          v-model="form.vision_provider"
          aria-label="视觉模型来源"
        >
          <option value="ollama">本地 Ollama</option>
          <option value="openai">本地兼容服务（llama.cpp / LM Studio）</option>
          <option value="cloud">云端兼容接口</option>
        </select></label
      >
      <label
        >视觉服务地址<input
          v-model="form.vision_base_url"
          type="url"
          :placeholder="
            form.vision_provider === 'ollama'
              ? 'http://127.0.0.1:11434'
              : form.vision_provider === 'openai'
                ? 'http://127.0.0.1:8081/v1'
                : 'https://服务商地址/v1'
          "
          required
      /></label>
      <label
        >视觉模型名称<input
          v-model="form.vision_model"
          placeholder="qwen3-vl:8b-instruct"
          required
      /></label>
      <template v-if="form.vision_provider === 'cloud'">
        <label
          >视觉接口密钥<input
            type="password"
            :value="visionKey || ''"
            @input="visionKey = $event.target.value"
            :placeholder="
              form.vision_api_key_configured
                ? '已配置；留空保留'
                : '填写视觉服务密钥'
            "
            autocomplete="new-password"
        /></label>
        <p class="help">
          云端视觉会发送需要识别的原页图片，请选择你认可的服务。视觉密钥独立保存。
        </p>
        <button
          v-if="
            form.vision_api_key_configured &&
            !form.vision_api_key_from_environment
          "
          type="button"
          class="text-button danger"
          @click="visionKey = ''"
        >
          清除视觉密钥（保存后生效）
        </button>
      </template>
      <p v-if="form.vision_provider === 'openai'" class="help">
        复用本机llama.cpp或LM
        Studio的视觉服务。默认无需密钥，服务须加载视觉投影文件；此接口不会自动下载模型。
      </p>
      <button
        type="button"
        class="secondary"
        :disabled="busy"
        @click="testVision"
      >
        保存并检查视觉连接
      </button>
      <details>
        <summary>文档理解高级设置</summary>
        <div class="stack section-gap">
          <label
            >单次识别超时（秒）<input
              v-model.number="form.vision_timeout"
              type="number"
              min="10"
              max="1200"
          /></label>
          <label
            >图片最长边（像素）<input
              v-model.number="form.vision_image_max_edge"
              type="number"
              min="1024"
              max="4096"
          /></label>
          <label
            >视觉上下文上限<input
              v-model.number="form.vision_context_tokens"
              type="number"
              min="4096"
              max="32768"
          /></label>
          <label
            >视觉输出上限<input
              v-model.number="form.vision_max_tokens"
              type="number"
              min="512"
              max="8192"
          /></label>
          <p class="help">
            默认Qwen3-VL-8B-Instruct。llama.cpp可让文字与视觉共享同一实例；Ollama会在识别后释放视觉模型。大页可提高输出上限，显存较小时控制上下文。
          </p>
        </div>
      </details>
    </section>
    <section class="panel stack">
      <h2>检索设置</h2>
      <label
        >嵌入模型<select v-model="form.embedding_model">
          <option value="auto">
            自动使用已安装的BGE-M3，未安装时沿用旧模型
          </option>
          <option value="bge-m3">BGE-M3（中英文统一稠密向量）</option>
          <option value="bge-v1.5">旧版BGE v1.5</option>
        </select></label
      >
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
        {{ status?.embedding_model }}
        {{ status?.embedding_ready ? "已就绪" : "尚未下载完整" }} ·
        {{ index?.message }}
      </p>
      <label class="check-label"
        ><input type="checkbox" v-model="form.use_reranker" />启用 BGE
        重排序</label
      >
      <p class="help">
        {{ status?.reranker_model }}
        {{
          status?.reranker_ready ? "已就绪" : "尚未下载完整"
        }}。自动快速检索也会按此设置重排；不可用时保留原召回结果并显示提示。
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
