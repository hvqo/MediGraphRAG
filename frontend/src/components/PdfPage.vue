<script setup lang="ts">
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { API } from "../api";
import "../pdf-text-layer.css";
const props = defineProps<{
  documentId: string;
  page: number;
  quote: string;
}>();
const canvas = ref<HTMLCanvasElement | null>(null),
  layer = ref<HTMLElement | null>(null),
  wrapper = ref<HTMLElement | null>(null),
  error = ref(""),
  matched = ref(false),
  stage = ref("initial");
let document: any,
  task: any,
  textLayer: any,
  generation = 0;
async function render() {
  const token = ++generation;
  error.value = "";
  matched.value = false;
  await nextTick();
  if (!canvas.value || !layer.value) return;
  try {
    task?.cancel();
    textLayer?.cancel();
    const pdf = await import("pdfjs-dist/legacy/build/pdf.mjs");
    pdf.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/legacy/build/pdf.worker.mjs",
      import.meta.url,
    ).href;
    if (document?.fingerprintId !== props.documentId) {
      await document?.destroy();
      document = await pdf.getDocument({
        url: `${API}/documents/${props.documentId}/source`,
      }).promise;
      document.fingerprintId = props.documentId;
    }
    if (token !== generation) return;
    const page = await document.getPage(
      Math.min(Math.max(1, props.page), document.numPages),
    );
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(
      1.6,
      Math.max(0.4, (wrapper.value?.clientWidth || 700) / base.width),
    );
    const viewport = page.getViewport({ scale });
    const ratio = window.devicePixelRatio || 1;
    canvas.value.width = viewport.width * ratio;
    canvas.value.height = viewport.height * ratio;
    canvas.value.style.width = `${viewport.width}px`;
    canvas.value.style.height = `${viewport.height}px`;
    stage.value = "canvas";
    task = page.render({
      canvasContext: canvas.value.getContext("2d")!,
      canvas: canvas.value,
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
    });
    await task.promise;
    stage.value = "text";
    if (token !== generation) return;
    layer.value.replaceChildren();
    layer.value.style.width = `${viewport.width}px`;
    layer.value.style.height = `${viewport.height}px`;
    layer.value.style.setProperty("--scale-factor", String(scale));
    layer.value.style.setProperty("--total-scale-factor", String(scale));
    textLayer = new pdf.TextLayer({
      textContentSource: await page.getTextContent(),
      container: layer.value,
      viewport,
    });
    await textLayer.render();
    stage.value = "highlight";
    const spans = Array.from(layer.value.querySelectorAll("span"));
    const normalized = (s: string) => s.replace(/\s+/g, "");
    const target = normalized(props.quote);
    const whole = spans.map((s) => normalized(s.textContent || "")).join("");
    const start = target ? whole.indexOf(target) : -1;
    if (start >= 0) {
      let cursor = 0;
      for (const span of spans) {
        const end = cursor + normalized(span.textContent || "").length;
        if (end > start && cursor < start + target.length)
          span.classList.add("pdf-highlight");
        cursor = end;
      }
      matched.value = true;
    }
  } catch (e) {
    if (
      token === generation &&
      !(e instanceof Error && e.name === "RenderingCancelledException")
    )
      error.value = "原始 PDF 加载失败，可以下载文件核对。";
  }
}
watch(() => [props.documentId, props.page, props.quote], render);
onMounted(render);
onBeforeUnmount(() => {
  generation++;
  task?.cancel();
  textLayer?.cancel();
  document?.destroy();
});
</script>
<template>
  <div ref="wrapper" class="pdf-reader" :data-stage="stage">
    <p v-if="error" class="notice error">{{ error }}</p>
    <p class="help">
      第 {{ page }} 页 ·
      {{
        matched
          ? "已高亮匹配原文"
          : quote
            ? "本页未定位到完整引句，请核对下方正文"
            : "可以选中文字"
      }}
    </p>
    <div class="pdf-page">
      <canvas ref="canvas"></canvas>
      <div ref="layer" class="textLayer"></div>
    </div>
  </div>
</template>
