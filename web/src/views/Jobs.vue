<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { store } from '../store'

const jobs = ref([])

async function load() {
  jobs.value = await api.get('/api/jobs?limit=100')
}

const stateColor = {
  queued: '#969799', running: '#1989fa', downloading: '#1989fa',
  slicing: '#1989fa', uploading: '#1989fa', printing: '#07c160',
  done: '#07c160', failed: '#ee0a24', cancelled: '#969799',
}

function progressText(j) {
  if (j.progress) return `${Math.round(j.progress * 100)}%`
  return ''
}

function syncFromWs() {
  // WS 推来的任务覆盖本地列表,并周期性全量刷新兜底
  load()
}

const onJob = (_t) => syncFromWs()
let timer = null
onMounted(() => {
  load()
  store.on(onJob)
  timer = setInterval(load, 8000)
})
onUnmounted(() => { store.off(onJob); clearInterval(timer) })
</script>

<template>
  <div class="pb-page">
    <van-nav-bar title="打印任务" />

    <van-empty v-if="!jobs.length" description="还没有任务。去「发现」页挑个模型一键打印吧" />

    <div v-for="j in jobs" :key="j.id" class="pb-card">
      <div class="pb-row">
        <van-tag :color="stateColor[j.state] || '#969799'">{{ j.state }}</van-tag>
        <div class="pb-grow pb-ellipsis" style="font-weight:600">
          #{{ j.id }} {{ j.kind === 'slice' ? '切片任务' : '一键打印' }}
        </div>
        <van-button v-if="!['done', 'failed', 'cancelled'].includes(j.state)"
                    size="mini" plain type="danger"
                    @click="api.post(`/api/jobs/${j.id}/cancel`).then(load)">
          取消
        </van-button>
      </div>
      <div class="pb-muted" style="margin-top:6px">
        {{ j.detail || j.error || '等待中' }}
        <span v-if="progressText(j)"> · {{ progressText(j) }}</span>
      </div>
      <van-progress v-if="j.progress > 0 && j.state !== 'done'"
                    :percentage="Math.round(j.progress * 100)" style="margin-top:8px" />
      <div class="pb-muted" style="margin-top:6px">
        {{ new Date(j.created_at).toLocaleString('zh-CN') }}
        <a v-if="j.result?.gcode_file_id" :href="`/api/library/files/${j.result.gcode_file_id}/download`"
           style="margin-left:8px">下载 G-code</a>
      </div>
    </div>
  </div>
</template>
