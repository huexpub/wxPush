<script setup>
import { ref } from 'vue'
import { notify } from '../store'

const props = defineProps({
  value: { type: String, default: '' },
  label: { type: String, default: '' },
})

const copied = ref(false)
let timer = 0

async function copy() {
  if (!props.value) return
  try {
    await navigator.clipboard.writeText(props.value)
  } catch {
    // 非 HTTPS / 旧浏览器：退回临时 textarea
    const area = document.createElement('textarea')
    area.value = props.value
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    document.body.removeChild(area)
  }
  copied.value = true
  notify('已复制到剪贴板', 'ok', 1600)
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
</script>

<template>
  <div class="code-block">
    <span v-if="label" class="cell-sub" style="margin-bottom: 4px">{{ label }}</span>{{ value }}
    <button class="btn sm copy" type="button" @click="copy">
      {{ copied ? '已复制' : '复制' }}
    </button>
  </div>
</template>
