<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { FOOTER } from './api'
import { logout, state, toasts } from './store'

const route = useRoute()

const nav = [
  { name: 'dashboard', label: '概览', path: '/', icon: 'M3 3h7v7H3zM12 3h7v4h-7zM12 9h7v7h-7zM3 12h7v7H3z' },
  { name: 'apps', label: '应用', path: '/apps', icon: 'M4 4h9v9H4zM13 13h7v7h-7zM11 13H4v7h7z' },
  { name: 'templates', label: '消息模板', path: '/templates', icon: 'M4 4h16v3H4zM4 9h16v3H4zM4 14h10v3H4z' },
  { name: 'hooks', label: 'Webhook', path: '/hooks', icon: 'M7 7h4v4H7zM13 13h4v4h-4zM11 9h4v4' },
  { name: 'messages', label: '消息历史', path: '/messages', icon: 'M4 5h16v11H9l-4 4v-4H4z' },
]

const title = computed(() => route.meta.title || '概览')
const authed = computed(() => state.authenticated)
const showShell = computed(() => route.name !== 'login' && authed.value)

onMounted(() => {
  const saved = localStorage.getItem('wxpush-theme')
  if (saved) document.documentElement.dataset.theme = saved
})

function toggleTheme() {
  const next = (document.documentElement.dataset.theme || 'dark') === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = next
  localStorage.setItem('wxpush-theme', next)
}

// 换页回到顶部，避免长列表滚动位置残留
watch(() => route.fullPath, () => window.scrollTo({ top: 0 }))

async function signOut() {
  await logout()
  window.location.hash = '#/login'
}
</script>

<template>
  <div v-if="showShell" class="shell">
    <aside class="sidebar">
      <div class="brand">
        <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" fill="none" stroke="var(--wk-border)" />
          <path d="M6 10h14v9H12l-4 4v-4H6z" fill="#3b82f6" />
          <path d="M14 14h13v9h-3v4l-4-4h-6z" fill="#3fb950" />
        </svg>
        <div class="brand-text">
          <b>WXPUSH</b>
          <span>企业微信推送后台</span>
        </div>
      </div>
      <nav class="nav">
        <RouterLink v-for="item in nav" :key="item.name" :to="item.path">
          <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path :d="item.icon" fill="none" stroke="currentColor" stroke-width="1.6" />
          </svg>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-foot">
        <button class="btn ghost sm" type="button" @click="toggleTheme">切换主题</button>
        <button v-if="state.gate" class="btn ghost sm" type="button" @click="signOut">退出登录</button>
        <span class="mono">v0.1.0</span>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <h1>{{ title }}</h1>
        <span class="crumb">{{ route.path }}</span>
      </header>
      <main class="content">
        <RouterView />
        <footer class="page-foot" v-html="FOOTER"></footer>
      </main>
    </div>
  </div>
  <RouterView v-else />

  <div class="toasts">
    <div v-for="toast in toasts" :key="toast.id" :class="['toast', toast.type]">{{ toast.message }}</div>
  </div>
</template>
