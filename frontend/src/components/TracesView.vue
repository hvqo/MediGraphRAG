<script setup lang="ts">
import { onActivated, ref } from "vue";
import { api, send } from "../api";
type Trace = {
  id: string;
  role: string;
  provider: string;
  model: string;
  template: string;
  status: string;
  duration: number;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string;
  created_at: string;
  input?: {
    system: string;
    prompt: string;
    source_revision: string;
    settings: Record<string, unknown>;
  };
  output?: unknown;
  sources_current?: boolean;
};
type Rejected = {
  id: string;
  job_id: string;
  reason: string;
  content: unknown;
  created_at: string;
};
const traces = ref<Trace[]>([]),
  rejected = ref<Rejected[]>([]),
  selected = ref<Trace | null>(null),
  replay = ref<unknown>(null),
  error = ref(""),
  busy = ref(false);
async function load() {
  [traces.value, rejected.value] = await Promise.all([
    api("/traces"),
    api("/rejected-candidates"),
  ]);
}
async function detail(id: string) {
  error.value = "";
  try {
    selected.value = await api("/traces/" + id);
    replay.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "加载失败";
  }
}
async function rerun() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    replay.value = await send(`/traces/${selected.value.id}/replay`, {});
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "回放失败";
  } finally {
    busy.value = false;
  }
}
onActivated(() => load().catch((e) => (error.value = e.message)));
</script>
<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">TRACE · INSPECT · REPLAY</p>
      <h1>看清每一次生成与拦截</h1>
      <p>保留模型、模板、原文集合版本、实际调用量、耗时与失败原因。</p>
    </div>
  </section>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <section class="panel stack">
    <div class="section-title">
      <h2>最近模型调用</h2>
      <button class="secondary" @click="load">刷新记录</button>
    </div>
    <p class="help">
      模型服务未返回调用量时显示“未返回”。回放会按原配置重新调用服务，云端可能产生费用。
    </p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>环节 / 模板</th>
            <th>模型</th>
            <th>耗时</th>
            <th>输入 / 输出量</th>
            <th>结果</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in traces" :key="r.id">
            <td>{{ new Date(r.created_at).toLocaleString() }}</td>
            <td>{{ r.role }} / {{ r.template }}</td>
            <td>{{ r.provider }} · {{ r.model }}</td>
            <td>{{ r.duration.toFixed(2) }} 秒</td>
            <td>
              {{ r.input_tokens ?? "未返回" }} /
              {{ r.output_tokens ?? "未返回" }}
            </td>
            <td>{{ r.status }}</td>
            <td>
              <button class="text-button" @click="detail(r.id)">
                检查调用
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!traces.length" class="empty">
      实际发起模型调用后，这里会记录运行详情。
    </p>
  </section>
  <section v-if="selected" class="panel stack section-gap">
    <p v-if="!selected.sources_current" class="notice">
      资料集合已变化；保留原记录供核对，回放已阻止。
    </p>
    <h2>{{ selected.model }} · {{ selected.template }}</h2>
    <p class="help">原文集合版本：{{ selected.input?.source_revision }}</p>
    <details>
      <summary>系统指令与实际提示词</summary>
      <pre class="diff"
        >{{ selected.input?.system }}
{{ selected.input?.prompt }}</pre
      >
    </details>
    <details>
      <summary>原模型配置</summary>
      <pre class="diff">{{
        JSON.stringify(selected.input?.settings, null, 2)
      }}</pre>
    </details>
    <h3>原始结构化结果</h3>
    <pre class="diff">{{ JSON.stringify(selected.output, null, 2) }}</pre>
    <p v-if="selected.error" class="notice error">{{ selected.error }}</p>
    <button class="primary" :disabled="busy" @click="rerun">
      用原配置再次调用
    </button>
    <p class="help">
      会检查原文版本；模型服务端权重和随机性可能变化。回放结果供排查，不会自动入题库。
    </p>
    <pre v-if="replay" class="diff">{{ JSON.stringify(replay, null, 2) }}</pre>
  </section>
  <section class="panel stack section-gap">
    <h2>被拦截的候选题</h2>
    <details v-for="r in rejected" :key="r.id">
      <summary>
        {{ new Date(r.created_at).toLocaleString() }} · {{ r.reason }}
      </summary>
      <p>生成任务 {{ r.job_id }}</p>
      <pre class="diff">{{ JSON.stringify(r.content, null, 2) }}</pre>
    </details>
    <p v-if="!rejected.length" class="empty">暂无被拦截的候选。</p>
  </section>
</template>
