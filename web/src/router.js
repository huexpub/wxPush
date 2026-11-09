import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Apps from './views/Apps.vue'
import Templates from './views/Templates.vue'
import Hooks from './views/Hooks.vue'
import Messages from './views/Messages.vue'
import Login from './views/Login.vue'
import { state, ensureSession } from './store'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard, meta: { title: '概览' } },
  { path: '/apps', name: 'apps', component: Apps, meta: { title: '应用' } },
  { path: '/templates', name: 'templates', component: Templates, meta: { title: '模板' } },
  { path: '/hooks', name: 'hooks', component: Hooks, meta: { title: 'Webhook' } },
  { path: '/messages', name: 'messages', component: Messages, meta: { title: '消息历史' } },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录', public: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

// hash 路由：后端不需要为每个页面配 rewrite，挂在子路径下也不受影响
const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach(async (to) => {
  await ensureSession()
  if (!to.meta.public && !state.authenticated) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && state.authenticated) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  const suffix = to.meta.title ? `${to.meta.title} · ` : ''
  document.title = `${suffix}WXPUSH`
})

export default router
