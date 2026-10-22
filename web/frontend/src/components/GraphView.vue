<script setup>
import { nextTick, onActivated, onBeforeUnmount, onMounted, ref } from "vue";
import { init, use } from "echarts/core";
import { GraphChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { AriaComponent } from "echarts/components";
import { send } from "../api";
import EvidenceList from "./EvidenceList.vue";
use([GraphChart, CanvasRenderer, AriaComponent]);
const keyword = ref(""),
  mode = ref("local"),
  data = ref(null),
  selected = ref([]),
  error = ref(""),
  busy = ref(false),
  container = ref(null);
let chart, observer;
async function search() {
  busy.value = true;
  error.value = "";
  selected.value = [];
  try {
    data.value = await send(
      mode.value === "local" ? "/graph/search" : "/graph/neo4j",
      { keyword: keyword.value },
    );
    await nextTick();
    draw();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function evidence(edge) {
  selected.value = (data.value?.evidence || []).filter((item) =>
    edge.evidence_ids.includes(item.id),
  );
}
function draw() {
  if (!container.value) return;
  if (!chart) {
    chart = init(container.value);
    chart.on("click", (e) => {
      if (e.dataType === "edge") evidence(e.data);
    });
  }
  const colors = ["#187d72", "#1b4669", "#c9984a", "#7c75a1", "#5996aa"];
  const categories = [
    ...new Set((data.value?.nodes || []).map((n) => n.category)),
  ];
  chart.setOption(
    {
      aria: { enabled: true },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          force: { repulsion: 500, edgeLength: [90, 180] },
          label: {
            show: true,
            position: "bottom",
            fontSize: 12,
            color: "#24434a",
          },
          edgeSymbol:
            mode.value === "neo4j" ? ["none", "arrow"] : ["none", "none"],
          data: (data.value?.nodes || []).map((n) => ({
            ...n,
            symbolSize: 34,
            itemStyle: {
              color: colors[categories.indexOf(n.category) % colors.length],
              borderWidth: 3,
              borderColor: "#fff",
            },
          })),
          links: (data.value?.links || []).map((e) => ({
            ...e,
            lineStyle: { color: "#9cb5b8", width: 1.4, curveness: 0.08 },
          })),
          edgeLabel: {
            show: (data.value?.links?.length || 0) < 20,
            formatter: (p) => p.data.label,
            fontSize: 10,
          },
        },
      ],
    },
    true,
  );
  chart.resize();
}
onMounted(() => {
  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(container.value);
  search();
});
onActivated(() => nextTick(() => chart?.resize()));
onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>

<template>
  <section class="page-intro">
    <div>
      <p class="eyebrow">EXPLORE THE CONNECTIONS</p>
      <h1>沿着关联，回到知识来源</h1>
      <p>探索医学概念在资料中的联系，点击连线查看支持它的原文。</p>
    </div>
  </section>
  <form class="toolbar" @submit.prevent="search">
    <input
      v-model="keyword"
      placeholder="输入医学关键词，或留空查看概览"
      aria-label="图谱关键词"
      maxlength="200"
    /><select v-model="mode" aria-label="图谱来源">
      <option value="local">资料共现图</option>
      <option value="neo4j">Neo4j 历史图谱</option></select
    ><button class="primary" :disabled="busy">
      {{ busy ? "查询中…" : "查看图谱" }}
    </button>
  </form>
  <p v-if="error" class="notice error" role="alert">{{ error }}</p>
  <p v-if="data" class="notice">{{ data.message }}</p>
  <div class="answer-layout section-gap">
    <section class="panel graph-panel">
      <div class="section-title">
        <h2>医学概念关系</h2>
        <span class="tag">{{ data?.nodes?.length || 0 }} 个概念</span>
      </div>
      <div ref="container" class="graph-canvas" aria-label="医学概念图谱"></div>
      <p v-if="!data?.nodes?.length" class="help">
        还没有可显示的概念。导入医学资料，或更换关键词后重试。
      </p>
      <div class="relation-list">
        <button
          v-for="(edge, index) in data?.links || []"
          :key="index"
          class="relation"
          @click="evidence(edge)"
        >
          {{ data.nodes.find((n) => n.id === edge.source)?.name }}
          <span>— {{ edge.label }} →</span>
          {{ data.nodes.find((n) => n.id === edge.target)?.name }}
        </button>
      </div>
    </section>
    <aside class="panel">
      <h2>关联的原文</h2>
      <EvidenceList :items="selected" />
      <p v-if="mode === 'neo4j'" class="help">
        历史图谱未关联文献的关系仅供浏览，不作为问答或出题的依据。
      </p>
    </aside>
  </div>
</template>
