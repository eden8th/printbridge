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
  return String(p.machine_id || '').split(' @')[0]
})

// 结构化打印参数:机型/喷头/材料/颜色/工艺
const COLOR_NAMES = {
  '#1a1a1a': '黑', '#f2f2f2': '白', '#8c8c8c': '灰', '#d32f2f': '红',
  '#f57c00': '橙', '#fbc02d': '黄', '#388e3c': '绿', '#1976d2': '蓝',
  '#7b1fa2': '紫', '#795548': '棕',
}
const printParams = computed(() => {
  const p = job.value?.payload || {}
  if (!p.bundle) return null
  const clean = (s) => (s ? String(s).split(' @')[0] : s)
  const machinePretty = clean(p.machine_id)
    .replace(/\s+\d+(?:\.\d+)?\s*nozzle\.json$/i, '')
    .replace(/\.json$/i, '')
  const m = String(p.machine_id || '').match(/(\d+(?:\.\d+)?)\s*nozzle/i)
  const fil = (p.filament_ids || []).map(clean)
  const color = (p.filament_colors || [])[0] || ''
  return {
    machine: machinePretty,
    nozzle: m ? `${m[1]} mm` : '',
    material: fil.join('、'),
    color,
    colorName: COLOR_NAMES[color.toLowerCase()] || '',
    process: clean(p.process_id),
    multi: (p.filament_ids || []).length > 1,
    cfsTnn: p.cfs_tnn || '',
  }
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
      <img v-if="job.result?.thumbnail_path" class="pb-thumbimg"
           :src="`/api/jobs/${job.id}/thumbnail`" alt="打印预览" />
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
      <h3 class="pb-title">打印参数</h3>
      <template v-if="printParams">
        <div class="pb-row">
          <span class="pb-muted" style="flex:none;width:72px">机型</span>
          <span class="pb-grow pb-ellipsis">{{ printParams.machine }}</span>
        </div>
        <div class="pb-row" v-if="printParams.nozzle">
          <span class="pb-muted" style="flex:none;width:72px">喷头</span>
          <span class="pb-grow">{{ printParams.nozzle }}</span>
        </div>
        <div class="pb-row" v-if="printParams.material">
          <span class="pb-muted" style="flex:none;width:72px">材料</span>
          <span class="pb-grow pb-ellipsis">{{ printParams.material }}</span>
        </div>
        <div class="pb-row" v-if="printParams.color">
          <span class="pb-muted" style="flex:none;width:72px">切片配色</span>
          <span class="pb-dot" :style="{ background: printParams.color }"></span>
          <span class="pb-grow">
            {{ printParams.colorName || '自定义' }}
            <span class="pb-muted">{{ printParams.color.toUpperCase() }}</span>
          </span>
        </div>
        <div class="pb-row" v-if="printParams.process">
          <span class="pb-muted" style="flex:none;width:72px">工艺</span>
          <span class="pb-grow pb-ellipsis">{{ printParams.process }}</span>
        </div>
        <div class="pb-row" v-if="printParams.cfsTnn">
          <span class="pb-muted" style="flex:none;width:72px">CFS 料道</span>
          <span class="pb-grow">打印前自动换料至 {{ printParams.cfsTnn }}</span>
        </div>
      </template>
      <div class="pb-row" v-else-if="sliceInfo">
        <span class="pb-muted" style="flex:none;width:72px">切片参数包</span>
        <span class="pb-grow pb-ellipsis">{{ sliceInfo }}</span>
      </div>
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
      <div class="pb-row" v-if="job.result?.estimated_sec">
        <span class="pb-muted" style="flex:none;width:72px">预估</span>
        <span class="pb-grow">{{ fmtMin(job.result.estimated_sec) }}
          · {{ Math.round(job.result.filament_grams || 0) }} g 耗材</span>
      </div>
      <div class="pb-row" v-if="job.result?.gcode_path || job.result?.gcode_file_id">
        <span class="pb-muted" style="flex:none;width:72px">G-code 产物</span>
        <span class="pb-grow"></span>
        <a :href="job.result?.gcode_file_id
            ? `/api/library/files/${job.result.gcode_file_id}/download`
            : `/api/jobs/${job.id}/gcode`">
          <van-button size="mini" plain type="primary">下载</van-button>
        </a>
      </div>
      <div class="pb-muted" style="margin-top:4px">
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
.pb-dot {
  width: 18px; height: 18px; border-radius: 50%; flex: none;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0;
}
.pb-thumbimg {
  width: 100%; border-radius: 8px; margin-top: 10px; background: #f2f3f5;
  max-height: 260px; object-fit: contain; display: block;
}
.pb-log {
  background: #0d1117; color: #c9d1d9; font-size: 11px; line-height: 1.5;
  padding: 10px; border-radius: 8px; overflow: auto; max-height: 320px;
  white-space: pre-wrap; word-break: break-all; margin: 8px 0 0;
}
</style>
