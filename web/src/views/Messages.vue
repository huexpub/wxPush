<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, formatTime, relativeTime } from '../api'
import { errorMessage, notifyErr, notifyOk } from '../store'
import Modal from '../components/Modal.vue'
import CopyBlock from '../components/CopyBlock.vue'

const loading = ref(true)
const items = ref([])
const total = ref(0)
const page = ref(0)
const limit = 20
const status = ref('')
const query = ref('')
const apps = ref([])
const appId = ref('')
const detail = ref(null)
const busy = ref('')

const pages = computed(() => Math.max(1, Math.ceil(total.value / limit)))
const canPrev = computed(() => page.value > 0)
const canNext = computed(() => page.value + 1 < pages.value)

const sourceText = computed(() => {
  if (!detail.value) return ''
  return JSON.stringify(detail.value.payload, null, 2)
})

async function load() {
  loading.value = true
  try {
    const res = await api.messages({
      limit,
      offset: page.value * limit,
      status: status.value,
      app_id: appId.value,
      q: query.value,
    })
    items.value = res?.items || []
    total.value = res?.total ?? 0
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const res = await api.apps()
    apps.value = res?.items || []
  } catch {
    /* 应用列表只是筛选项，失败不影响主表 */
  }
}

async function openDetail(item) {
  detail.value = item
}

async function resend() {
  if (!detail.value || busy.value) return
  busy.value = 'resend'
  try {
    await api.resendMessage(detail.value.id)
    notifyOk('已重新发送')
    detail.value = null
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    busy.value = ''
  }
}

async function removeOne() {
  if (!detail.value) return
  if (!confirm('删除这条记录？')) return
  try {
    await api.deleteMessage(detail.value.id)
    notifyOk('记录已删除')
    detail.value = null
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function clearAll() {
  if (!confirm(`清空全部 ${total.value} 条历史记录？不可恢复。`)) return
  try {
    const res = await api.clearMessages()
    notifyOk(`已删除 ${res.deleted} 条记录`)
    page.value = 0
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

let searchTimer = 0
watch([status, appId], () => {
  page.value = 0
  load()
})
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 0
    load()
  }, 320)
})

onMounted(async () => {
  await Promise.all([load(), loadMeta()])
})
</script>

<template>
  <div>
    <div class="toolbar">
      <input v-model="query" class="input" style="width: 220px" placeholder="搜索内容 / payload" />
      <select v-model="status" class="select" style="width: 130px">
        <option value="">全部状态</option>
        <option value="success">成功</option>
        <option value="failed">失败</option>
      </select>
      <select v-model="appId" class="select" style="width: 180px">
        <option value="">全部应用</option>
        <option v-for="app in apps" :key="app.id" :value="app.id">{{ app.name }}</option>
      </select>
      <button class="btn" type="button" @click="load">刷新</button>
      <div class="toolbar-spacer" />
      <span style="font-size: 12px; color: var(--wk-muted-2)">共 {{ total }} 条</span>
      <button class="btn danger" type="button" :disabled="!total" @click="clearAll">清空</button>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!items.length" class="panel">
      <div class="empty">
        <b>没有匹配的记录</b>
        调用一次 webhook，成功与失败都会记在这里。
      </div>
    </div>

    <div v-else class="panel">
      <div class="panel-body tight table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>时间</th>
              <th>应用</th>
              <th>Webhook</th>
              <th>模板</th>
              <th>类型</th>
              <th>接收人</th>
              <th>状态</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id" class="message-row" @click="openDetail(item)">
              <td :title="formatTime(item.created_at)">
                {{ relativeTime(item.created_at) }}
                <span class="cell-sub">{{ formatTime(item.created_at).slice(11) }}</span>
              </td>
              <td>{{ item.app_name || '—' }}</td>
              <td>{{ item.hook_name || '—' }}</td>
              <td>{{ item.template_name || '—' }}</td>
              <td><span class="tag">{{ item.msg_type }}</span></td>
              <td class="mono" style="font-size: 12px">{{ item.touser }}</td>
              <td>
                <span class="tag" :class="item.status === 'success' ? 'ok' : 'fail'">
                  {{ item.status === 'success' ? '成功' : '失败' }}
                </span>
              </td>
              <td class="mono">{{ item.duration_ms }}ms</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <span>第 {{ page + 1 }} / {{ pages }} 页</span>
        <div class="toolbar-spacer" />
        <button class="btn sm" type="button" :disabled="!canPrev" @click="page--; load()">上一页</button>
        <button class="btn sm" type="button" :disabled="!canNext" @click="page++; load()">下一页</button>
      </div>
    </div>

    <Modal v-if="detail" title="消息详情" wide @close="detail = null">
      <dl class="kv" style="margin-bottom: 16px">
        <dt>记录 ID</dt>
        <dd class="mono">{{ detail.id }}</dd>
        <dt>时间</dt>
        <dd>{{ formatTime(detail.created_at) }}</dd>
        <dt>应用 / 模板</dt>
        <dd>{{ detail.app_name }} · {{ detail.template_name }}</dd>
        <dt>Webhook</dt>
        <dd>{{ detail.hook_name }}</dd>
        <dt>接收人</dt>
        <dd class="mono">{{ detail.touser }}</dd>
        <dt>来源 IP</dt>
        <dd class="mono">{{ detail.ip || '—' }}</dd>
        <dt>状态</dt>
        <dd>
          <span class="tag" :class="detail.status === 'success' ? 'ok' : 'fail'">
            {{ detail.status === 'success' ? '成功' : '失败' }}
          </span>
          <span class="mono" style="margin-left: 8px">{{ detail.duration_ms }}ms</span>
        </dd>
      </dl>

      <div v-if="detail.error" class="login-error" style="white-space: pre-wrap">
        {{ detail.error }}
      </div>

      <div class="field">
        <label>调用方传的变量</label>
        <CopyBlock :value="sourceText" />
      </div>

      <div class="field">
        <label>实际发送的内容</label>
        <CopyBlock :value="detail.rendered || '（渲染失败，无内容）'" />
      </div>

      <div v-if="detail.response" class="field">
        <label>企业微信响应</label>
        <CopyBlock :value="detail.response" />
      </div>

      <template #footer>
        <button class="btn danger" type="button" @click="removeOne">删除记录</button>
        <div class="toolbar-spacer" />
        <button class="btn" type="button" @click="detail = null">关闭</button>
        <button
          class="btn primary"
          type="button"
          :disabled="busy === 'resend' || !detail.hook_id"
          @click="resend"
        >
          {{ busy === 'resend' ? '发送中…' : '用同样内容重发' }}
        </button>
      </template>
    </Modal>
  </div>
</template>
