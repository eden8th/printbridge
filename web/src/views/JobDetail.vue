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

// 流水线失败原因的友好诊断
function diagnoseError(e) {
  const s = String(e || '')
  if (/凭证|token/i.test(s)) return 'MakerWorld 凭证问题:去「设置」页更新 token 后重试'
  if (/下载/.test(s)) return '模型下载失败:多为网络波动或凭证失效,重试通常可解决'
  if (/切片失败|切片器/.test(s)) return '切片引擎执行失败:下方日志含具体原因,把日志发给我们可以修复'
  if (/换料|料道/.test(s)) return 'CFS 换料失败:确认料道已装料、打印机在线后重试'
  if (/上传/.test(s)) return 'G-code 上传失败:检查打印机是否在线'
  return ''
}
const failureHint = computed(() => diagnoseError(job.value?.error))

// 打印机侧最终状态的简短文案
const PRINT_STATUS_TEXT = {
  completed: '打印完成',
  error: '打印机报错终止',
  klippy_shutdown: 'Klipper 紧急关机,打印中断',
  cancelled: '已被取消',
}
const printStatusText = computed(() =>
  PRINT_STATUS_TEXT[job.value?.result?.print_status]
  || job.value?.result?.print_status || '')

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
    await showConfirmDialog({
      title: '取消打印',
      message: '确定取消该任务?打印机上正在进行的打印将同时中止,已消耗的耗材不退回。',
    })
  } catch { return }
  try {
    await api.post(`/api/jobs/${route.params.id}/cancel`)
    showSuccessToast('已取消')
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

const canRetry = computed(() =>
  job.value && ['failed', 'cancelled'].includes(job.value.state))

// 重新打印:已完成的打印任务,用同样参数开一个新任务
const canReprint = computed(() =>
  job.value && job.value.kind === 'pipeline' && job.value.state === 'done'
  && !(job.value.payload?.slice_only || job.value.payload?.download_only))

async function retry() {
  try {
    await api.post(`/api/jobs/${route.params.id}/retry`)
    showSuccessToast('已重新入队')
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

async function reprint() {
  try {
    const r = await api.post(`/api/jobs/${route.params.id}/reprint`)
    showSuccessToast(`已创建新任务 #${r.job_id}`)
    router.replace(`/jobs/${r.job_id}`)
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

    <div class="pb-cols">
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
      <!-- 打印机侧最终结果(print_watch 回写):完成绿卡 / 故障橙卡 -->
      <div v-if="job.result?.print_status === 'completed'"
           style="margin-top:10px;background:#e8f7ee;color:#07c160;border-radius:8px;padding:10px;font-size:13px">
        🎉 打印完成,取件时留意热床仍在高温
      </div>
      <div v-else-if="job.result?.print_status && job.result.print_status !== 'in_progress'"
           style="margin-top:10px;background:#fff7f0;color:#ff976a;border-radius:8px;padding:10px;font-size:13px">
        <div>⚠️ 打印机侧结果:{{ printStatusText }}</div>
        <div v-if="job.result.print_diagnosis" style="margin-top:4px">
          💡 {{ job.result.print_diagnosis }}
        </div>
        <van-button v-if="canReprint" size="mini" plain type="primary" style="margin-top:6px"
                    @click="reprint">重新打印</van-button>
      </div>
      <div v-if="job.error" style="margin-top:10px;color:#ee0a24;font-size:13px">
        ⚠️ {{ job.error }}
        <div v-if="failureHint" class="pb-muted" style="color:#969799;margin-top:2px">
          💡 {{ failureHint }}
        </div>
      </div>
      <div v-if="job.result?.print_status" class="pb-row"
           style="margin-top:10px;padding:8px;background:#f7f8fa;border-radius:8px">
        <span class="pb-muted" style="flex:none;width:72px">打印结果</span>
        <span class="pb-grow" style="font-size:13px"
              :style="{ color: job.result.print_status === 'completed' ? '#07c160' : '#ee0a24' }">
          {{ job.result.print_diagnosis }}
        </span>
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
    </div><!-- /pb-cols -->

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
      <template v-else>
        <van-button v-if="canReprint" block round type="primary" style="flex:1"
                    @click="reprint">重新打印</van-button>
        <van-button v-if="canRetry" block round type="primary" style="flex:1"
                    @click="retry">重试任务</van-button>
        <van-button block round type="danger" plain style="flex:1"
                    @click="del">删除任务</van-button>
      </template>
    </div>
    <div v-if="canRetry && job.retries" class="pb-muted" style="margin-top:6px;text-align:center">
      已重试 {{ job.retries }} 次
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
