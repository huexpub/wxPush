<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { errorMessage, notifyErr, notifyOk } from '../store'
import Modal from '../components/Modal.vue'

const loading = ref(true)
const items = ref([])
const editing = ref(null)
const saving = ref(false)
const testing = ref('')
const form = reactive({
  name: '',
  corp_id: '',
  agent_id: '',
  secret: '',
  default_touser: '',
})

function reset() {
  Object.assign(form, { name: '', corp_id: '', agent_id: '', secret: '', default_touser: '' })
}

async function load() {
  loading.value = true
  try {
    const res = await api.apps()
    items.value = res?.items || []
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = { id: null }
  reset()
}

function openEdit(app) {
  editing.value = app
  Object.assign(form, {
    name: app.name,
    corp_id: app.corp_id,
    agent_id: app.agent_id,
    secret: '',
    default_touser: app.default_touser,
  })
}

function close() {
  editing.value = null
  reset()
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    if (editing.value?.id) {
      const body = {
        name: form.name,
        corp_id: form.corp_id,
        agent_id: form.agent_id,
        default_touser: form.default_touser,
      }
      if (form.secret) body.secret = form.secret
      await api.updateApp(editing.value.id, body)
      notifyOk('应用已更新')
    } else {
      await api.createApp({ ...form })
      notifyOk('应用已创建')
    }
    close()
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function toggle(app) {
  try {
    await api.updateApp(app.id, { enabled: !app.enabled })
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function remove(app) {
  if (!confirm(`删除应用「${app.name}」？关联的 webhook 会一起删除，历史记录保留。`)) return
  try {
    await api.deleteApp(app.id)
    notifyOk('应用已删除')
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function test(app) {
  testing.value = app.id
  try {
    await api.testApp(app.id)
    notifyOk('测试消息已发送，去企业微信看看')
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    testing.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <button class="btn primary" type="button" @click="openCreate">新建应用</button>
      <span class="hint" style="font-size: 12px; color: var(--wk-muted-2)">
        企业微信后台 → 应用管理 → 自建应用，拿到 AgentId 与 Secret
      </span>
    </div>

    <div v-if="loading" class="empty">加载中…</div>

    <div v-else-if="!items.length" class="panel">
      <div class="empty">
        <b>还没有应用</b>
        先建一个：填企业 ID（我的企业 → 企业信息）、AgentId、Secret。
      </div>
    </div>

    <div v-else class="panel">
      <div class="panel-body tight table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>名称</th>
              <th>企业 ID</th>
              <th>AgentId</th>
              <th>Secret</th>
              <th>默认接收人</th>
              <th>状态</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="app in items" :key="app.id">
              <td>{{ app.name }}</td>
              <td class="mono">{{ app.corp_id }}</td>
              <td class="mono">{{ app.agent_id }}</td>
              <td class="mono">{{ app.secret_hint }}</td>
              <td class="mono">{{ app.default_touser || '@all' }}</td>
              <td>
                <span class="tag" :class="app.enabled ? 'ok' : 'off'">
                  {{ app.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td style="text-align: right; white-space: nowrap">
                <div class="btn-group" style="justify-content: flex-end">
                  <button class="btn sm" type="button" :disabled="testing === app.id" @click="test(app)">
                    {{ testing === app.id ? '发送中…' : '测试' }}
                  </button>
                  <button class="btn sm" type="button" @click="openEdit(app)">编辑</button>
                  <button class="btn sm" type="button" @click="toggle(app)">
                    {{ app.enabled ? '停用' : '启用' }}
                  </button>
                  <button class="btn sm danger" type="button" @click="remove(app)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal
      v-if="editing"
      :title="editing.id ? '编辑应用' : '新建应用'"
      @close="close"
    >
      <div class="field">
        <label>名称</label>
        <input v-model="form.name" class="input" placeholder="如：构建通知机器人" />
      </div>
      <div class="grid-2">
        <div class="field">
          <label>企业 ID（corpid）</label>
          <input v-model="form.corp_id" class="input mono" placeholder="ww1234567890abcdef" />
        </div>
        <div class="field">
          <label>AgentId</label>
          <input v-model="form.agent_id" class="input mono" placeholder="1000002" />
        </div>
      </div>
      <div class="field">
        <label>Secret</label>
        <input
          v-model="form.secret"
          class="input mono"
          type="password"
          :placeholder="editing.id ? `留空 = 不修改（当前 ${editing.secret_hint}）` : '应用 Secret'"
        />
        <span class="help">Secret 会加密存储，界面上只显示末四位。</span>
      </div>
      <div class="field">
        <label>默认接收人</label>
        <input v-model="form.default_touser" class="input mono" placeholder="留空 = @all，多个用 | 分隔" />
        <span class="help">企业微信要求用 <code>|</code> 分隔多个 UserID，例如 <code>zhangsan|lisi</code>。</span>
      </div>

      <template #footer>
        <button class="btn" type="button" @click="close">取消</button>
        <button class="btn primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </Modal>
  </div>
</template>
