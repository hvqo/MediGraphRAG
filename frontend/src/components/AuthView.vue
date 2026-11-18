<script setup lang="ts">
import { ref } from "vue";
import { useAuth } from "../stores/auth";
const auth = useAuth();
const username = ref(""),
  password = ref(""),
  register = ref(false),
  busy = ref(false),
  error = ref("");
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await auth.authenticate(username.value, password.value, register.value);
    password.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="auth-page">
    <section class="auth-card">
      <p class="eyebrow">MEDIGRAPH RAG</p>
      <h1>{{ register ? "创建你的医学学习空间" : "欢迎回来" }}</h1>
      <p>上传资料、直接提问、生成练习。文档和题目随账号保存。</p>
      <form @submit.prevent="submit">
        <label
          >账号<input
            v-model="username"
            name="username"
            autocomplete="username"
            required
            minlength="3"
            maxlength="32"
            pattern="[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}"
            placeholder="3–32位字母、数字或 . _ -"
        /></label>
        <label
          >密码<input
            v-model="password"
            name="password"
            type="password"
            :autocomplete="register ? 'new-password' : 'current-password'"
            required
            minlength="12"
            maxlength="128"
            placeholder="至少12位"
        /></label>
        <p v-if="error" class="notice error" role="alert">{{ error }}</p>
        <button class="primary" :disabled="busy">
          {{ busy ? "请稍候…" : register ? "注册并进入" : "登录" }}
        </button>
      </form>
      <button
        v-if="auth.registration"
        class="text-button"
        @click="
          register = !register;
          error = '';
        "
      >
        {{ register ? "已有账号？去登录" : "还没有账号？创建一个" }}
      </button>
      <small>忘记密码请联系网站管理员。每个账号拥有独立资料库。</small>
    </section>
  </main>
</template>
<style>
.auth-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: radial-gradient(ellipse at top left, #d7eee8, #f5f7f5 65%);
}
.auth-card {
  width: min(100%, 440px);
  padding: clamp(24px, 5vw, 44px);
  border: 1px solid #dce6e0;
  border-radius: 20px;
  background: white;
  box-shadow: 0 20px 80px #164f3d0e;
}
.auth-card h1 {
  font-size: 26px;
  margin: 12px 0;
}
.auth-card p,
.auth-card small {
  color: #60716a;
  line-height: 1.7;
}
.auth-card form {
  display: grid;
  gap: 20px;
  margin: 28px 0 16px;
}
.auth-card label {
  display: grid;
  gap: 8px;
}
.auth-card input {
  width: 100%;
  min-width: 0;
}
.auth-card small {
  display: block;
  margin-top: 24px;
}
</style>
