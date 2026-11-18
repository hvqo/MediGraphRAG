import { defineStore } from "pinia";
import { ref } from "vue";
import { api, send, setCsrf } from "../api";

type User = { id: string; username: string; role: string };
export const useAuth = defineStore("auth", () => {
  const ready = ref(false),
    enabled = ref(false),
    registration = ref(false);
  const user = ref<User | null>(null),
    error = ref("");
  async function initialize() {
    try {
      const data = await api("/auth/status");
      enabled.value = data.enabled;
      registration.value = data.registration_enabled;
      user.value = data.user;
      setCsrf(data.csrf_token);
      error.value = "";
      ready.value = true;
    } catch (e) {
      error.value = (e as Error).message;
    }
  }
  async function authenticate(
    username: string,
    password: string,
    register: boolean,
  ) {
    const data = await send(register ? "/auth/register" : "/auth/login", {
      username,
      password,
    });
    setCsrf(data.csrf_token);
    user.value = data.user;
  }
  function expired() {
    user.value = null;
    setCsrf("");
  }
  async function logout() {
    await send("/auth/logout", {});
    expired();
  }
  window.addEventListener("medigraph-session-expired", expired);
  return {
    ready,
    enabled,
    registration,
    user,
    error,
    initialize,
    authenticate,
    logout,
    expired,
  };
});
