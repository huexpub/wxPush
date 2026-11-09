<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { API, BASE, api } from '../api'
import { errorMessage, notifyErr, notifyOk } from '../store'
import Modal from '../components/Modal.vue'
import CopyBlock from '../components/CopyBlock.vue'

const loading = ref(true)
const items = ref([])
const apps = ref([])
const templates = ref([])
const editing = ref(null)
const saving = ref(false)

// 新建成功 / 查看 key 时展示一次完整 key
const revealed = ref(null)

const form = reactive({ name: '', app_id: '', template_id: '' })

function webhookUrl(key) {
  return `${location.origin}${BASE}${API}/hook/${key}`
}

const samplePayload = computed(() => {
  // 优先用「正在预览的那条 hook」的模板；编辑弹窗里则用表单选中的模板
  const templateId = revealed.value?.template_id || form.template_id
  const template = templates.value.find((item) => item.id === templateId)
  const vars = template?.variables || []
  const data = {}
  for (const name of vars) {
    if (name.includes('.')) continue
    if (name === 'time') data[name] = new Date().toLocaleString('zh-CN')
    else if (name === 'url') data[name] = 'https://example.com/runs/1'
    else if (name === 'status') data[name] = '成功'
    else data[name] = `示例 ${name}`
  }
  if (!Object.keys(data).length) {
    data.title = '示例标题'
    data.content = '示例内容'
  }
  return JSON.stringify(data, null, 2)
})

/** 单行 JSON，塞进 curl -d '...' 时用 */
const inlinePayload = computed(() => JSON.stringify(JSON.parse(samplePayload.value)))

async function load() {
  loading.value = true
  try {
    const [hooksRes, appsRes, templatesRes] = await Promise.all([
      api.hooks(),
      api.apps(),
      api.templates(),
    ])
    items.value = hooksRes.items
    apps.value = appsRes.items
    templates.value = templatesRes.items
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  if (!apps.value.length) return notifyErr('请先创建一个应用')
  if (!templates.value.length) return notifyErr('请先创建一个消息模板')
  editing.value = { id: null }
  Object.assign(form, {
    name: '',
    app_id: apps.value[0].id,
    template_id: templates.value[0].id,
  })
}

function openEdit(hook) {
  editing.value = hook
  Object.assign(form, { name: hook.name, app_id: hook.app_id, template_id: hook.template_id })
}

function close() {
  editing.value = null
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    if (editing.value?.id) {
      await api.updateHook(editing.value.id, { ...form })
      notifyOk('Webhook 已更新')
      close()
    } else {
      const created = await api.createHook({ ...form })
      close()
      revealed.value = created
      notifyOk('Webhook 已创建，key 只在这里完整显示')
    }
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function reveal(hook) {
  try {
    const res = await api.revealHook(hook.id)
    revealed.value = { ...hook, key: res.key }
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function rotate(hook) {
  if (!confirm(`轮换「${hook.name}」的 key？旧 key 立即失效。`)) return
  try {
    const res = await api.rotateHook(hook.id)
    revealed.value = { ...hook, key: res.key }
    notifyOk('key 已轮换')
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function toggle(hook) {
  try {
    await api.updateHook(hook.id, { enabled: !hook.enabled })
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

async function remove(hook) {
  if (!confirm(`删除 webhook「${hook.name}」？`)) return
  try {
    await api.deleteHook(hook.id)
    notifyOk('webhook 已删除')
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <button class="btn primary" type="button" @click="openCreate">新建 Webhook</button>
      <span style="font-size: 12px; color: var(--wk-muted-2)">
        每个 webhook = 一个应用 + 一个模板 + 一把独立 key
      </span>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!items.length" class="panel">
      <div class="empty">
        <b>还没有 webhook</b>
        选好应用与模板后创建，把生成的地址交给 gitea action 或任意脚本。
      </div>
    </div>

    <div v-else class="panel">
      <div class="panel-body tight table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>名称</th>
              <th>应用</th>
              <th>模板</th>
              <th>Key</th>
              <th>调用</th>
              <th>最近使用</th>
              <th>状态</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="hook in items" :key="hook.id">
              <td>{{ hook.name }}</td>
              <td>
                {{ hook.app_name }}
                <span class="cell-sub">{{ hook.msg_type }}</span>
              </td>
              <td>{{ hook.template_name }}</td>
              <td class="mono" style="font-size: 12px">{{ hook.key_hint }}</td>
              <td class="mono">{{ hook.use_count }}</td>
              <td class="mono" style="font-size: 12px">
                {{
                  hook.last_used_at
                    ? new Date(hook.last_used_at * 1000).toLocaleString('zh-CN')
                    : '—'
                }}
              </td>
              <td>
                <span class="tag" :class="hook.enabled ? 'ok' : 'off'">
                  {{ hook.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td style="text-align: right; white-space: nowrap">
                <div class="btn-group" style="justify-content: flex-end">
                  <button class="btn sm" type="button" @click="reveal(hook)">调用方式</button>
                  <button class="btn sm" type="button" @click="openEdit(hook)">编辑</button>
                  <button class="btn sm" type="button" @click="toggle(hook)">
                    {{ hook.enabled ? '停用' : '启用' }}
                  </button>
                  <button class="btn sm" type="button" @click="rotate(hook)">轮换</button>
                  <button class="btn sm danger" type="button" @click="remove(hook)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal v-if="editing" :title="editing.id ? '编辑 Webhook' : '新建 Webhook'" @close="close">
      <div class="field">
        <label>名称</label>
        <input v-model="form.name" class="input" placeholder="如：gitea 构建通知" />
      </div>
      <div class="field">
        <label>应用</label>
        <select v-model="form.app_id" class="select">
          <option v-for="app in apps" :key="app.id" :value="app.id">
            {{ app.name }}（{{ app.agent_id }}）
          </option>
        </select>
      </div>
      <div class="field">
        <label>消息模板</label>
        <select v-model="form.template_id" class="select">
          <option v-for="template in templates" :key="template.id" :value="template.id">
            {{ template.name }} · {{ template.msg_type }}
          </option>
        </select>
      </div>

      <template #footer>
        <button class="btn" type="button" @click="close">取消</button>
        <button class="btn primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </Modal>

    <Modal
      v-if="revealed"
      title="调用这个 webhook"
      wide
      @close="revealed = null"
    >
      <div class="field">
        <label>Webhook Key</label>
        <CopyBlock :value="revealed.key" />
      </div>
      <div class="field">
        <label>POST 地址</label>
        <CopyBlock :value="webhookUrl(revealed.key)" />
        <span class="help">
          也支持 header <code>X-Wxpush-Key</code>，或 POST 到
          <code>{{ BASE }}{{ API }}/hook</code> 时带 <code>?key=</code>。
        </span>
      </div>
      <div class="field">
        <label>请求体（模板需要的变量）</label>
        <CopyBlock :value="samplePayload" />
      </div>
      <div class="field">
        <label>curl</label>
        <CopyBlock
          :value="`curl -X POST '${webhookUrl(revealed.key)}' \\\n  -H 'Content-Type: application/json' \\\n  -d '${inlinePayload}'`"
        />
      </div>
      <div class="field">
        <label>gitea action 片段</label>
        <CopyBlock
          :value="`- name: 推送企业微信\n  run: |\n    curl -sSf -X POST '${webhookUrl(revealed.key)}' \\\n      -H 'Content-Type: application/json' \\\n      -d '${inlinePayload}'`"
        />
      </div>
      <div class="field">
        <label>其它语言（Python）</label>
        <CopyBlock
          :value="`import requests\nrequests.post(\n    '${webhookUrl(revealed.key)}',\n    json=${inlinePayload},\n    timeout=10,\n).raise_for_status()`"
        />
      </div>
    </Modal>
  </div>
</template>
