<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, formatTime, relativeTime } from '../api'
import { errorMessage, notifyErr } from '../store'
import Modal from '../components/Modal.vue'
import CopyBlock from '../components/CopyBlock.vue'

const loading = ref(true)
const stats = ref(null)
const hooks = ref([])
const templates = ref([])
const selectedHook = ref(null)
const revealKey = ref('')
const revealBusy = ref(false)

const samplePayload = computed(() => {
  const template = templates.value.find((t) => t.id === selectedHook.value?.template_id)
  const vars = template?.variables?.length ? template.variables : ['title', 'content']
  const data = {}
  for (const name of vars) {
    const leaf = name.split('.').pop()
    data[leaf] = `示例 ${leaf}`
  }
  return JSON.stringify(data, null, 2)
})

const hookUrl = computed(() => {
  if (!selectedHook.value) return ''
  const base = window.__WXPUSH_BASE__ || ''
  const apiPrefix = window.__WXPUSH_API__ || '/api'
  return `${location.origin}${base}${apiPrefix}/hook/wxp_xxx`
})

async function load() {
  loading.value = true
  try {
    const [statsRes, hooksRes, templatesRes] = await Promise.all([
      api.stats(),
      api.hooks(),
      api.templates(),
    ])
    stats.value = statsRes
    hooks.value = hooksRes?.items || []
    templates.value = templatesRes?.items || []
  } catch (err) {
    stats.value = null
    notifyErr(errorMessage(err))
  } finally {
    loading.value = false
  }
}

async function openHook(hook) {
  selectedHook.value = hook
  revealKey.value = hook.key_hint
  revealBusy.value = true
  try {
    const res = await api.revealHook(hook.id)
    revealKey.value = res.key
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    revealBusy.value = false
  }
}

function closeHook() {
  selectedHook.value = null
  revealKey.value = ''
}

onMounted(load)
</script>

<template>
  <div>
    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!stats" class="empty">
      <b>加载失败</b>
      无法读取统计数据，检查服务是否可用后刷新页面。
    </div>

    <template v-else>
      <div class="stat-grid">
        <div class="stat">
          <div class="label">应用</div>
          <div class="value">{{ stats.apps }}</div>
          <div class="meta">企业微信自建应用</div>
        </div>
        <div class="stat">
          <div class="label">模板</div>
          <div class="value">{{ stats.templates }}</div>
          <div class="meta">text / markdown / textcard / news</div>
        </div>
        <div class="stat">
          <div class="label">Webhook</div>
          <div class="value">{{ stats.hooks }}</div>
          <div class="meta">对外接入口</div>
        </div>
        <div class="stat">
          <div class="label">24 小时消息</div>
          <div class="value">{{ stats.messages_24h }}</div>
          <div class="meta">7 天 {{ stats.messages_7d }} · 失败 {{ stats.failed_7d }}</div>
        </div>
      </div>

      <section class="panel" style="margin-top: 18px">
        <div class="panel-head">
          <h2>最近消息</h2>
          <span class="hint">共 {{ stats.messages }} 条历史</span>
          <div class="toolbar-spacer" />
          <RouterLink class="btn sm" to="/messages">查看全部</RouterLink>
        </div>
        <div v-if="!stats.recent.length" class="empty">
          <b>还没有消息</b>
          建一个 webhook，往它 POST 一段 JSON 就会出现在这里。
        </div>
        <div v-else class="panel-body tight table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>时间</th>
                <th>应用</th>
                <th>Webhook</th>
                <th>类型</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in stats.recent" :key="item.id">
                <td :title="formatTime(item.created_at)">{{ relativeTime(item.created_at) }}</td>
                <td>{{ item.app_name || '—' }}</td>
                <td>{{ item.hook_name || '—' }}</td>
                <td><span class="tag">{{ item.msg_type }}</span></td>
                <td>
                  <span class="tag" :class="item.status === 'success' ? 'ok' : 'fail'">
                    {{ item.status === 'success' ? '成功' : '失败' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>Webhook 接入</h2>
          <span class="hint">点任意一条查看完整 key 与调用示例</span>
        </div>
        <div v-if="!hooks.length" class="empty">
          <b>还没有 webhook</b>
          去 <RouterLink to="/hooks" style="color: var(--wk-accent)">Webhook</RouterLink> 页创建一个。
        </div>
        <div v-else class="panel-body tight table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>名称</th>
                <th>应用</th>
                <th>Key</th>
                <th>调用次数</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="hook in hooks" :key="hook.id" class="message-row" @click="openHook(hook)">
                <td>{{ hook.name }}</td>
                <td>{{ hook.app_name }}</td>
                <td class="mono">{{ hook.key_hint }}</td>
                <td class="mono">{{ hook.use_count }}</td>
                <td style="text-align: right">
                  <span class="tag" :class="hook.enabled ? 'ok' : 'off'">
                    {{ hook.enabled ? '启用' : '停用' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <Modal v-if="selectedHook" title="Webhook 调用" wide @close="closeHook">
      <div class="field">
        <label>POST 地址（把 wxp_xxx 换成你的 key）</label>
        <CopyBlock :value="hookUrl" />
      </div>
      <div class="field">
        <label>Webhook Key</label>
        <CopyBlock :value="revealBusy ? '读取中…' : revealKey" />
        <span class="help">Key 加密保存在数据库里，这里可以随时复制。</span>
      </div>
      <div class="field">
        <label>请求体示例</label>
        <CopyBlock :value="samplePayload" />
      </div>
      <div class="field">
        <label>curl</label>
        <CopyBlock
          :value="`curl -X POST '${hookUrl.replace('wxp_xxx', revealKey)}' \\\n  -H 'Content-Type: application/json' \\\n  -d '${samplePayload.replace(/\n/g, '')}'`"
        />
      </div>
    </Modal>
  </div>
</template>
