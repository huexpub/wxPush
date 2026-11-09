<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login, errorMessage } from '../store'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    router.replace(next.startsWith('/') ? next : '/')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="submit">
      <h1>WXPUSH</h1>
      <p class="sub">企业微信应用消息推送后台</p>

      <div v-if="error" class="login-error">{{ error }}</div>

      <div class="field">
        <label for="login-user">用户名</label>
        <input
          id="login-user"
          v-model="username"
          class="input"
          autocomplete="username"
          placeholder="未配置用户名时留空"
        />
      </div>

      <div class="field">
        <label for="login-pass">密码</label>
        <input
          id="login-pass"
          v-model="password"
          class="input"
          type="password"
          autocomplete="current-password"
          placeholder="WXPUSH_ADMIN_PASSWORD"
        />
      </div>

      <button class="btn primary" style="width: 100%; margin-top: 6px" type="submit" :disabled="busy">
        {{ busy ? '登录中…' : '登录' }}
      </button>
    </form>
  </div>
</template>
