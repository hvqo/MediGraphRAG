export const API = (import.meta.env.VITE_API_BASE_URL || "/api").replace(
  /\/$/,
  "",
);
let csrfToken = "";
export function setCsrf(value: string) {
  csrfToken = value || "";
}
// Existing JavaScript views retain their dynamic response shape during gradual migration.
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(API + path, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(csrfToken &&
      options.method &&
      !["GET", "HEAD"].includes(options.method.toUpperCase())
        ? { "X-CSRF-Token": csrfToken }
        : {}),
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (
      response.status === 401 &&
      !["/auth/login", "/auth/register"].includes(path)
    )
      window.dispatchEvent(new Event("medigraph-session-expired"));
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
