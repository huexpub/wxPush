// 运行时配置由后端注入（见 wxpush/web.py），没有注入时按本地开发默认值处理。
const boot = window

export const BASE = boot.__WXPUSH_BASE__ ?? ''
export const API = boot.__WXPUSH_API__ ?? '/api'
export const GATE = boot.__WXPUSH_GATE__ ?? false
export const FOOTER = boot.__WXPUSH_FOOTER__ ?? 'WXPUSH @ 2026'

export class ApiError extends Error {
  constructor(message, { status = 0, code = '', detail = '' } = {}) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

// 会话过期时由 store 注册回调，把用户送回登录页（api.js 不能反向依赖 store）
let onUnauthorized = null

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

async function request(method, path, body) {
  const init = { method, headers: {}, credentials: 'same-origin' }
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let response
  try {
    response = await fetch(`${API}${path}`, init)
  } catch (err) {
    throw new ApiError('网络错误，无法连接服务', { code: 'network' })
  }
  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { message: text }
    }
  }
  if (!response.ok) {
    const message = data?.message || `请求失败（HTTP ${response.status}）`
    // 登录接口自己会返回 401，那是「密码错了」，不该触发跳转
    if (response.status === 401 && !path.startsWith('/auth/login') && onUnauthorized) {
      onUnauthorized()
    }
    throw new ApiError(message, {
      status: response.status,
      code: data?.error || '',
      detail: data?.detail || '',
    })
  }
  return data
}

export const http = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body ?? {}),
  patch: (path, body) => request('PATCH', path, body ?? {}),
  del: (path) => request('DELETE', path),
}

export const api = {
  session: () => http.get('/auth/session'),
  login: (username, password) => http.post('/auth/login', { username, password }),
  logout: () => http.post('/auth/logout'),

  stats: () => http.get('/stats'),

  apps: () => http.get('/apps'),
  createApp: (body) => http.post('/apps', body),
  updateApp: (id, body) => http.patch(`/apps/${id}`, body),
  deleteApp: (id) => http.del(`/apps/${id}`),
  testApp: (id, content) => http.post(`/apps/${id}/test`, { content }),

  templates: () => http.get('/templates'),
  createTemplate: (body) => http.post('/templates', body),
  updateTemplate: (id, body) => http.patch(`/templates/${id}`, body),
  deleteTemplate: (id) => http.del(`/templates/${id}`),
  previewTemplate: (body) => http.post('/templates/preview', body),

  hooks: () => http.get('/hooks'),
  createHook: (body) => http.post('/hooks', body),
  updateHook: (id, body) => http.patch(`/hooks/${id}`, body),
  deleteHook: (id) => http.del(`/hooks/${id}`),
  revealHook: (id) => http.get(`/hooks/${id}/key`),
  rotateHook: (id) => http.post(`/hooks/${id}/rotate`),

  messages: (params = {}) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== '' && value !== null && value !== undefined) query.set(key, value)
    }
    const suffix = query.toString()
    return http.get(`/messages${suffix ? `?${suffix}` : ''}`)
  },
  message: (id) => http.get(`/messages/${id}`),
  deleteMessage: (id) => http.del(`/messages/${id}`),
  clearMessages: () => http.del('/messages'),
  resendMessage: (id) => http.post(`/messages/${id}/resend`),
}

/** 拼出可访问的 webhook 完整地址 */
export function webhookUrl(key) {
  return `${location.origin}${BASE}${API}/hook/${key}`
}

export function formatTime(seconds) {
  if (!seconds) return '—'
  const date = new Date(seconds * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function relativeTime(seconds) {
  if (!seconds) return '—'
  const diff = Math.floor(Date.now() / 1000) - seconds
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`
  return formatTime(seconds).slice(0, 10)
}
