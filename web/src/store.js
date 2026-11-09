import { reactive } from 'vue'
import { api, GATE, setUnauthorizedHandler } from './api'

export const state = reactive({
  ready: false,
  authenticated: !GATE,
  gate: GATE,
  subject: null,
  user: '',
})

// 任意请求拿到 401（cookie 过期 / 被清）就退回登录页，而不是停在一堆报错里
setUnauthorizedHandler(() => {
  state.authenticated = false
  state.subject = null
  if (typeof location !== 'undefined' && !location.hash.startsWith('#/login')) {
    location.hash = '#/login'
  }
})

export async function ensureSession(force = false) {
  if (state.ready && !force) return state
  try {
    const info = await api.session()
    state.gate = info.gate
    state.authenticated = info.authenticated
    state.subject = info.subject
    state.user = info.user || ''
  } catch {
    state.authenticated = !GATE
  } finally {
    state.ready = true
  }
  return state
}

export async function login(username, password) {
  await api.login(username, password)
  await ensureSession(true)
}

export async function logout() {
  try {
    await api.logout()
  } finally {
    state.authenticated = !state.gate
    state.subject = null
  }
}

// ---- 轻量 toast：一个全局队列，App.vue 负责渲染 ----
export const toasts = reactive([])
let toastId = 0

export function notify(message, type = 'info', timeout = 3600) {
  const id = ++toastId
  toasts.push({ id, message, type })
  setTimeout(() => {
    const index = toasts.findIndex((item) => item.id === id)
    if (index >= 0) toasts.splice(index, 1)
  }, timeout)
}

export const notifyOk = (message) => notify(message, 'ok')
export const notifyErr = (message) => notify(message, 'error', 5200)

export function errorMessage(err) {
  if (!err) return '未知错误'
  return err.message || String(err)
}
