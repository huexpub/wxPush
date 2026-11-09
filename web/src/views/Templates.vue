<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { errorMessage, notifyErr, notifyOk } from '../store'
import Modal from '../components/Modal.vue'
import CopyBlock from '../components/CopyBlock.vue'

const MSG_TYPES = [
  { value: 'text', label: '纯文本', hint: '最简单，支持换行；不渲染任何标记。' },
  { value: 'markdown', label: 'Markdown', hint: '支持 **加粗**、[链接](url)、> 引用、列表。' },
  {
    value: 'textcard',
    label: '文本卡片',
    hint: 'JSON 结构：{"title","description","url","btntxt"}，可点进链接。',
  },
  {
    value: 'news',
    label: '图文消息',
    hint: 'JSON 结构：{"articles":[{"title","description","url","picurl"}]}，最多 8 条。',
  },
]

const DEFAULTS = {
  text: '{{ title }}\n{{ content }}',
  markdown: '**{{ title }}**\n\n{{ content }}',
  textcard: JSON.stringify(
    { title: '{{ title }}', description: '{{ content }}', url: '{{ url }}', btntxt: '详情' },
    null,
    2
  ),
  news: JSON.stringify(
    { articles: [{ title: '{{ title }}', description: '{{ content }}', url: '{{ url }}' }] },
    null,
    2
  ),
}

const loading = ref(true)
const items = ref([])
const editing = ref(null)
const saving = ref(false)
const preview = ref('')
const previewError = ref('')
const previewData = ref('{\n  "title": "构建完成",\n  "content": "bfs 镜像已发布到 ghcr",\n  "url": "https://example.com"\n}')

const form = reactive({ name: '', description: '', msg_type: 'text', content: '' })

const hint = computed(
  () => MSG_TYPES.find((item) => item.value === form.msg_type)?.hint || ''
)

function variablesOf(text) {
  const found = []
  const re = /\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*default\s+"[^"]*")?\s*\}\}/g
  let match
  while ((match = re.exec(text || ''))) {
    if (!found.includes(match[1])) found.push(match[1])
  }
  return found
}

const variables = computed(() => variablesOf(form.content))

async function load() {
  loading.value = true
  try {
    const res = await api.templates()
    items.value = res?.items || []
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    loading.value = false
  }
}

function fillPreviewData(content) {
  const data = {}
  for (const name of variablesOf(content)) {
    if (name.includes('.')) continue
    if (name === 'url') data[name] = 'https://example.com'
    else if (name === 'status') data[name] = '成功'
    else if (name === 'project') data[name] = 'bfs'
    else if (name === 'branch') data[name] = 'main'
    else if (name === 'commit') data[name] = 'a1b2c3d'
    else if (name === 'time') data[name] = new Date().toLocaleString('zh-CN')
    else data[name] = `示例 ${name}`
  }
  if (!Object.keys(data).length) {
    data.title = '构建完成'
    data.content = 'bfs 镜像已发布到 ghcr'
    data.url = 'https://example.com'
  }
  previewData.value = JSON.stringify(data, null, 2)
}

function openCreate() {
  editing.value = { id: null }
  Object.assign(form, { name: '', description: '', msg_type: 'text', content: DEFAULTS.text })
  preview.value = ''
  previewError.value = ''
  fillPreviewData(form.content)
}

function openEdit(template) {
  editing.value = template
  Object.assign(form, {
    name: template.name,
    description: template.description,
    msg_type: template.msg_type,
    content: template.content,
  })
  preview.value = ''
  previewError.value = ''
  fillPreviewData(template.content)
}

function close() {
  editing.value = null
  preview.value = ''
  previewError.value = ''
}

function onTypeChange() {
  form.content = DEFAULTS[form.msg_type] || ''
  preview.value = ''
  fillPreviewData(form.content)
}

async function runPreview() {
  previewError.value = ''
  let data = {}
  try {
    data = previewData.value.trim() ? JSON.parse(previewData.value) : {}
  } catch {
    previewError.value = '示例数据不是合法 JSON'
    return
  }
  if (!data.time) data.time = new Date().toLocaleString('zh-CN')
  try {
    const res = await api.previewTemplate({
      msg_type: form.msg_type,
      content: form.content,
      data,
    })
    preview.value = res.rendered
  } catch (err) {
    previewError.value = errorMessage(err)
    preview.value = ''
  }
}

function insertVar(name) {
  form.content += ` {{ ${name} }}`
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    if (editing.value?.id) {
      await api.updateTemplate(editing.value.id, { ...form })
      notifyOk('模板已更新')
    } else {
      await api.createTemplate({ ...form })
      notifyOk('模板已创建')
    }
    close()
    await load()
  } catch (err) {
    notifyErr(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function remove(template) {
  if (!confirm(`删除模板「${template.name}」？引用它的 webhook 会一起删除。`)) return
  try {
    await api.deleteTemplate(template.id)
    notifyOk('模板已删除')
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
      <button class="btn primary" type="button" @click="openCreate">新建模板</button>
      <span style="font-size: 12px; color: var(--wk-muted-2)">
        模板用 <code>&#123;&#123; 变量 &#125;&#125;</code> 取值，调用方只需 POST 这些 key
      </span>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!items.length" class="panel">
      <div class="empty">
        <b>还没有模板</b>
        建一个「构建完成」模板：正文写 <code>&#123;&#123; title &#125;&#125;</code> 和
        <code>&#123;&#123; content &#125;&#125;</code>。
      </div>
    </div>

    <div v-else class="panel">
      <div class="panel-body tight table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>变量</th>
              <th>更新时间</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>
                {{ item.name }}
                <span v-if="item.description" class="cell-sub">{{ item.description }}</span>
              </td>
              <td><span class="tag">{{ item.msg_type }}</span></td>
              <td class="mono" style="font-size: 12px">
                {{ item.variables.length ? item.variables.join(', ') : '—' }}
              </td>
              <td class="mono" style="font-size: 12px">
                {{ new Date(item.updated_at * 1000).toLocaleString('zh-CN') }}
              </td>
              <td style="text-align: right; white-space: nowrap">
                <div class="btn-group" style="justify-content: flex-end">
                  <button class="btn sm" type="button" @click="openEdit(item)">编辑</button>
                  <button class="btn sm danger" type="button" @click="remove(item)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal
      v-if="editing"
      :title="editing.id ? '编辑模板' : '新建模板'"
      wide
      @close="close"
    >
      <div class="grid-2">
        <div class="field">
          <label>名称</label>
          <input v-model="form.name" class="input" placeholder="如：构建完成通知" />
        </div>
        <div class="field">
          <label>消息类型</label>
          <select v-model="form.msg_type" class="select" @change="onTypeChange">
            <option v-for="type in MSG_TYPES" :key="type.value" :value="type.value">
              {{ type.label }}
            </option>
          </select>
        </div>
      </div>

      <div class="field">
        <label>说明</label>
        <input v-model="form.description" class="input" placeholder="给未来的自己留一句话（可选）" />
      </div>

      <div class="field">
        <label>模板正文</label>
        <textarea v-model="form.content" class="textarea" rows="10" spellcheck="false" />
        <span class="help">{{ hint }}</span>
        <div v-if="variables.length" class="var-list" style="margin-top: 6px">
          <span class="cell-sub" style="width: 100%">模板变量：</span>
          <button
            v-for="name in variables"
            :key="name"
            class="var-chip"
            type="button"
            title="再插入一次"
            @click="insertVar(name)"
          >
            {{ name }}
          </button>
        </div>
      </div>

      <div class="split">
        <div class="field">
          <label>示例数据（JSON）</label>
          <textarea
            v-model="previewData"
            class="textarea"
            rows="8"
            spellcheck="false"
          />
          <div class="btn-group">
            <button class="btn sm" type="button" @click="runPreview">渲染预览</button>
          </div>
        </div>
        <div class="field">
          <label>渲染结果</label>
          <div v-if="previewError" class="login-error">{{ previewError }}</div>
          <CopyBlock v-if="preview" :value="preview" />
          <div v-else class="code-block" style="color: var(--wk-muted-2)">
            点「渲染预览」看结果
          </div>
        </div>
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
