<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()
const jobs = ref([])

async function load() {
  try {
    jobs.value = await api.get('/api/jobs?limit=100')
  } catch (e) {
    showFailToast(e.message)
  }
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

async function cancelJob(j) {
  try {
    await api.post(`/api/jobs/${j.id}/cancel`)
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

function delJob(j) {
  showConfirmDialog({ title: '删除任务', message: `确定删除任务 #${j.id}?记录与日志将一并删除。` })
    .then(async () => {
      await api.del(`/api/jobs/${j.id}`)
      showSuccessToast('已删除')
      load()
    }).catch(() => {})
}

function syncFromWs() {
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

    <div v-for="j in jobs" :key="j.id" class="pb-card clickable" @click="router.push(`/jobs/${j.id}`)">
      <div class="pb-row">
        <van-tag :color="stateColor[j.state] || '#969799'">{{ j.state }}</van-tag>
        <span v-if="(j.payload?.filament_colors || [])[0]" class="pb-listdot"
              :style="{ background: j.payload.filament_colors[0] }"></span>
        <div class="pb-grow pb-ellipsis" style="font-weight:600">
          #{{ j.id }} {{ j.kind === 'slice' ? '切片任务' : '一键打印' }}
        </div>
        <van-button v-if="!['done', 'failed', 'cancelled'].includes(j.state)"
                    size="mini" plain type="warning" @click.stop="cancelJob(j)">
          取消
        </van-button>
        <van-button v-else size="mini" plain type="danger" @click.stop="delJob(j)">
          删除
        </van-button>
      </div>
      <div class="pb-muted" style="margin-top:6px">
        {{ j.detail || j.error || '等待中' }}
        <span v-if="progressText(j)"> · {{ progressText(j) }}</span>
      </div>
      <van-progress v-if="j.progress > 0 && j.state !== 'done'"
                    :percentage="Math.round(j.progress * 100)" style="margin-top:8px" />
      <div class="pb-muted pb-row" style="margin-top:6px">
        <span class="pb-grow">{{ new Date(j.created_at).toLocaleString('zh-CN') }}</span>
        <span>详情 <van-icon name="arrow" /></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.clickable { cursor: pointer; }
.pb-listdot {
  width: 14px; height: 14px; border-radius: 50%; flex: none;
  border: 1.5px solid #fff; box-shadow: 0 0 0 1px #dcdee0;
}
</style>
