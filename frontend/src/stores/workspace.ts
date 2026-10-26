import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api";
import type { Summary } from "../types";
export const useWorkspace = defineStore("workspace", () => {
  const status = ref<{ provider: string } | null>(null),
    summary = ref<Summary>({ documents: 0, chunks: 0, pending: 0 }),
    error = ref("");
  async function refresh() {
    try {
      [status.value, summary.value] = await Promise.all([
        api("/status"),
        api("/summary"),
      ]);
      error.value = "";
    } catch {
      error.value = "无法连接后端服务，请先启动应用。";
    }
  }
  return { status, summary, error, refresh };
});
