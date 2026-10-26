<script setup>
import { API } from "../api";
defineProps({ items: { type: Array, default: () => [] }, selected: String });
</script>

<template>
  <div class="evidence-list">
    <div v-if="!items.length" class="empty small">
      检索后，这里会显示原文和出处。
    </div>
    <details
      v-for="(item, index) in items"
      :key="item.id"
      class="evidence-card"
      :open="selected === item.id"
    >
      <summary>
        <span class="source-number">{{ index + 1 }}</span
        ><span
          ><strong>{{ item.title }}</strong
          ><small>{{ item.filename }} · {{ item.location }}</small></span
        ><span class="muted">⌄</span>
      </summary>
      <p class="source-text">{{ item.text }}</p>
      <p v-if="item.source_metadata" class="help">
        {{ item.source_metadata.source }} {{ item.source_metadata.edition }}
        {{ item.source_metadata.year }} {{ item.source_metadata.scope }}
      </p>
      <RouterLink
        :to="{
          name: 'reader',
          params: { id: item.document_id },
          query: {
            chunk: item.id,
            page: item.page || 1,
            quote: item.text.slice(0, 400),
          },
        }"
        >定位原文 ↗</RouterLink
      >
      <a
        :href="`${API}/documents/${item.document_id}/source`"
        target="_blank"
        rel="noopener"
        >下载原始资料 ↗</a
      >
    </details>
  </div>
</template>
