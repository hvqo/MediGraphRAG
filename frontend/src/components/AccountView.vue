<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, send } from "../api";
import { useAuth } from "../stores/auth";
const auth = useAuth(),
  usage = ref<any>(null),
  users = ref<any[]>([]);
const current = ref(""),
  password = ref(""),
  message = ref(""),
  busy = ref(false);
const newUsername = ref(""),
  newPassword = ref("");
const resetId = ref(""),
  resetPassword = ref("");
async function perform(action: () => Promise<void>) {
  busy.value = true;
  message.value = "";
  try {
    await action();
  } catch (e) {
    message.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function refresh() {
  usage.value = await api("/auth/usage");
  if (auth.user?.role === "admin") users.value = await api("/auth/admin/users");
}
async function changePassword() {
  await perform(async () => {
    await send("/auth/password", {
      current_password: current.value,
      new_password: password.value,
    });
    current.value = "";
    password.value = "";
    auth.expired();
  });
}
async function createUser() {
  await perform(async () => {
    await send("/auth/admin/users", {
      username: newUsername.value,
      password: newPassword.value,
    });
    newUsername.value = "";
    newPassword.value = "";
    message.value = "账号已创建";
    await refresh();
  });
}
async function toggle(user: any) {
  await perform(async () => {
    await send(
      `/auth/admin/users/${user.id}`,
      { disabled: !user.disabled },
      "PUT",
    );
    await refresh();
  });
}
async function reset() {
  await perform(async () => {
    await send(`/auth/admin/users/${resetId.value}/password`, {
      password: resetPassword.value,
    });
    resetPassword.value = "";
    resetId.value = "";
    message.value = "密码已重置，该用户需重新登录";
  });
}
onMounted(() => perform(refresh));
</script>
<template>
  <section class="account-page">
    <h1>账号与登录</h1>
    <p>
      {{ auth.user?.username }} ·
      {{ auth.user?.role === "admin" ? "管理员" : "个人账号" }} ·
      资料仅当前账号可见
    </p>
    <p v-if="usage">
      今日模型调用 {{ usage.model_calls_today }} /
      {{ usage.model_calls_per_day }} 次（UTC零点重置）；资料容量
      {{ usage.storage_mb }} MB。
    </p>
    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <form @submit.prevent="changePassword">
      <h2>修改密码</h2>
      <label
        >当前密码<input
          v-model="current"
          type="password"
          autocomplete="current-password"
          required
          maxlength="128"
      /></label>
      <label
        >新密码<input
          v-model="password"
          type="password"
          autocomplete="new-password"
          required
          minlength="12"
          maxlength="128"
      /></label>
      <small>修改后所有设备都会退出登录。</small>
      <button :disabled="busy">保存新密码</button>
    </form>
    <template v-if="auth.user?.role === 'admin'">
      <h2>网站账号管理</h2>
      <p>管理员配置公共模型、管理账号；每位用户的文档和题目仍独立保存。</p>
      <form @submit.prevent="createUser">
        <h3>创建普通账号</h3>
        <label
          >账号<input
            v-model="newUsername"
            required
            minlength="3"
            maxlength="32"
            autocomplete="off"
        /></label>
        <label
          >初始密码<input
            v-model="newPassword"
            type="password"
            required
            minlength="12"
            maxlength="128"
            autocomplete="new-password"
        /></label>
        <button :disabled="busy">创建账号</button>
      </form>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>账号</th>
              <th>角色</th>
              <th>状态</th>
              <th>管理</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.username }}</td>
              <td>{{ user.role }}</td>
              <td>{{ user.disabled ? "已停用" : "正常" }}</td>
              <td>
                <button
                  :disabled="busy || user.id === auth.user.id"
                  @click="toggle(user)"
                >
                  {{ user.disabled ? "启用" : "停用" }}
                </button>
                <button
                  :disabled="busy"
                  @click="
                    resetId = user.id;
                    resetPassword = '';
                  "
                >
                  重置密码
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <form v-if="resetId" @submit.prevent="reset">
        <label
          >新密码<input
            v-model="resetPassword"
            type="password"
            required
            minlength="12"
            maxlength="128"
            autocomplete="new-password" /></label
        ><button :disabled="busy">确认重置并退出该账号所有设备</button
        ><button type="button" @click="resetId = ''">取消</button>
      </form>
    </template>
  </section>
</template>
<style scoped>
.account-page {
  max-width: 860px;
}
form {
  display: grid;
  gap: 14px;
  max-width: 440px;
  margin: 24px 0 36px;
}
label {
  display: grid;
  gap: 8px;
}
.table-scroll {
  overflow-x: auto;
}
td button {
  margin: 4px;
}
</style>
