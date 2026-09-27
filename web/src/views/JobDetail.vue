<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const route = useRoute()
const router = useRouter()
const job = ref(null)
const log = ref('')
const loading = ref(true)

const isEnded = computed(() =>
  job.value && ['done', 'failed', 'cancelled'].includes(job.value.state))
const isFailed = computed(() => job.value?.state === 'failed')

// 一键打印流水线的阶段展示
const steps = computed(() => {
  if (!job.value) return []
  if (job.value.kind === 'slice') return [{ key: 'slice', label: '切片' }]
  return [
    { key: 'download', label: '下载模型' },
    { key: 'slice', label: '切片' },
    { key: 'upload', label: '上传打印机' },
    { key: 'print', label: '开始打印' },
  ]
})

function stateToStep(s) {
  if (job.value.kind === 'slice') return { downloading: 0, slicing: 0 }[s] ?? -1
  return { downloading: 0, slicing: 1, uploading: 2, printing: 3 }[s] ?? -1
}

const activeStep = computed(() => {
  if (!job.value) return -1
  if (job.value.state === 'done') return steps.value.length
  if (job.value.state === 'failed' || job.value.state === 'cancelled') {
    // 失败/取消时按最后阶段文案定位到出错环节
    const d = job.value.detail || ''
    if (d.includes('切片')) return 1
    if (d.includes('上传')) return 2
    if (d.includes('打印')) return 3
    return 0
  }
  return stateToStep(job.value.state)
})

function stepIcon(i) {
  if (isFailed.value && i === activeStep.value) return 'close'
  if (i < activeStep.value || (job.value?.state === 'done')) return 'checked'
  if (i === activeStep.value) return 'clock-o'
  return 'circle'
}
function stepColor(i) {
  if (isFailed.value && i === activeStep.value) return '#ee0a24'
  if (i < activeStep.value || job.value?.state === 'done') return '#07c160'
  if (i === activeStep.value) return '#1989fa'
  return '#c8c9cc'
}

const sliceInfo = computed(() => {
  const p = job.value?.payload || {}
  if (!p.bundle) return ''
  const clean = (s) => (s ? String(s).split(' @')[0] : s)
  const parts = [clean(p.machine_id),
    ...(p.filament_ids || []).map(clean), clean(p.process_id)].filter(Boolean)
  const colors = p.filament_colors || []
  return parts.join(' · ') + (colors[0] ? ` · 颜色 ${colors[0]}` : '')
})

const fmtMin = (s) => (s ? `${Math.round(s / 60)} 分钟` : '')

async function load() {
  try {
    job.value = await api.get(`/api/jobs/${route.params.id}`)
    if (job.value.has_log) {
      const l = await api.get(`/api/jobs/${route.params.id}/log`)
      log.value = l.log || ''
    }
  } catch (e) {
    showFailToast(e.message)
  } finally {
    loading.value = false
  }
}

async function cancel() {
  try {
    await api.post(`/api/jobs/${route.params.id}/cancel`)
    showSuccessToast('已取消')
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

function del() {
  showConfirmDialog({ title: '删除任务', message: '删除后任务记录与日志不可恢复,确定?' })
    .then(async () => {
      await api.del(`/api/jobs/${route.params.id}`)
      showSuccessToast('已删除')
      router.replace('/jobs')
    }).catch(() => {})
}

const onJob = (data) => {
  if (data.id === Number(route.params.id)) load()
}
let timer = null
onMounted(() => {
  load()
  store.on(onJob)
  timer = setInterval(load, 6000)
})
onUnmounted(() => { store.off(onJob); clearInterval(timer) })
</script>

<template>
  <div class="pb-page" v-if="job">
    <van-nav-bar :title="`任务 #${job.id}`" left-arrow @click-left="router.back()" />

    <!-- 状态与阶段 -->
    <div class="pb-card">
      <div class="pb-row">
        <span style="font-weight:600">{{ job.kind === 'slice' ? '切片任务' : '一键打印' }}</span>
        <span class="pb-grow"></span>
        <span class="pb-muted">{{ job.detail || job.state }}</span>
      </div>
      <div class="pb-steps">
        <div v-for="(s, i) in steps" :key="s.key" class="pb-row" style="padding:6px 0">
          <van-icon :name="stepIcon(i)" :color="stepColor(i)" size="18" />
          <span class="pb-grow" :style="{ color: stepColor(i) }">{{ s.label }}</span>
        </div>
      </div>
      <van-progress v-if="job.progress > 0 && !isEnded"
                    :percentage="Math.round(job.progress * 100)" />
      <div v-if="job.error" style="margin-top:10px;color:#ee0a24;font-size:13px">
        ⚠️ {{ job.error }}
      </div>
    </div>

    <!-- 详情信息 -->
    <div class="pb-card" style="font-size:13px;line-height:2">
      <div class="pb-row" v-if="job.model_file_name">
        <span class="pb-muted" style="flex:none;width:72px">模型文件</span>
        <span class="pb-grow pb-ellipsis">{{ job.model_file_name }}</span>
        <a v-if="job.model_file_id"
           :href="`/api/library/files/${job.model_file_id}/download`">
          <van-button size="mini" plain>下载源文件</van-button>
        </a>
      </div>
      <div class="pb-row" v-if="job.printer_name">
        <span class="pb-muted" style="flex:none;width:72px">目标打印机</span>
        <span class="pb-grow">{{ job.printer_name }}</span>
      </div>
      <div class="pb-row" v-if="sliceInfo">
        <span class="pb-muted" style="flex:none;width:72px">切片参数</span>
        <span class="pb-grow pb-ellipsis">{{ sliceInfo }}</span>
      </div>
      <div class="pb-row" v-if="job.result?.estimated_sec">
        <span class="pb-muted" style="flex:none;width:72px">预估耗时</span>
        <span class="pb-grow">{{ fmtMin(job.result.estimated_sec) }}
          · {{ Math.round(job.result.filament_grams || 0) }} g 耗材</span>
      </div>
      <div class="pb-row" v-if="job.result?.gcode_file_id">
        <span class="pb-muted" style="flex:none;width:72px">G-code 产物</span>
        <span class="pb-grow"></span>
        <a :href="`/api/library/files/${job.result.gcode_file_id}/download`">
          <van-button size="mini" plain type="primary">下载 G-code</van-button>
        </a>
      </div>
      <div class="pb-muted">
        创建于 {{ new Date(job.created_at).toLocaleString('zh-CN') }}
      </div>
    </div>

    <!-- 切片日志 -->
    <div class="pb-card" v-if="log">
      <div class="pb-row">
        <h3 class="pb-title pb-grow" style="margin:0">切片日志</h3>
        <van-button size="mini" plain @click="load">刷新</van-button>
      </div>
      <pre class="pb-log">{{ log }}</pre>
    </div>

    <!-- 操作 -->
    <div class="pb-row" style="margin-top:12px;gap:10px">
      <van-button v-if="!isEnded" block round type="warning" plain @click="cancel">取消任务</van-button>
      <van-button v-if="isEnded" block round type="danger" plain @click="del">删除任务</van-button>
    </div>
  </div>

  <van-loading v-else-if="loading" center style="margin-top:40%">加载中...</van-loading>
  <van-empty v-else description="任务不存在" />
</template>

<style scoped>
.pb-steps { margin-top: 8px; }
.pb-log {
  background: #0d1117; color: #c9d1d9; font-size: 11px; line-height: 1.5;
  padding: 10px; border-radius: 8px; overflow: auto; max-height: 320px;
  white-space: pre-wrap; word-break: break-all; margin: 8px 0 0;
}
</style>
