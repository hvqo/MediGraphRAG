export const API = (import.meta.env.VITE_API_BASE_URL || "/api").replace(
  /\/$/,
  "",
);
// Existing JavaScript views retain their dynamic response shape during gradual migration.
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(API + path, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join("；")
          : "请求失败，请检查服务状态",
    );
  }
  return data as T;
}
export const send = <T = any>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });
