<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const route = useRoute()
const router = useRouter()
const printers = ref([])
const profiles = ref([])
const cfsInfo = ref(null)

const id = computed(() => Number(route.params.id))
const p = computed(() => printers.value.find((x) => x.id === id.value))
const tel = computed(() => store.printers[id.value] || p.value?.telemetry || null)

const stateColor = {
  printing: '#07c160', idle: '#1989fa', paused: '#ff976a',
  error: '#ee0a24', offline: '#969799',
}
const stateText = {
  printing: '打印中', idle: '空闲', paused: '已暂停',
  error: '故障', offline: '离线',
}

const modelName = computed(() => {
  const key = p.value?.settings?.model
  const b = profiles.value.find((x) => x.key === key)
  return b?.name || key || '未设置'
})

// 控制按钮按状态可用性
const st = computed(() => tel.value?.state || '')
const canPause = computed(() => st.value === 'printing')
const canResume = computed(() => st.value === 'paused')
const canStop = computed(() => ['printing', 'paused'].includes(st.value))

async function control(action) {
  if (action === 'stop') {
    try {
      await showConfirmDialog({
        title: '停止打印',
        message: '确定停止当前打印?已消耗的耗材不退回。',
      })
    } catch { return }
  }
  try {
    await api.post(`/api/printers/${id.value}/control`, { action })
    showSuccessToast(`已发送 ${action}`)
  } catch (e) {
    showFailToast(e.message)
  }
}

// 摄像头快照(5 秒自动刷新,失败降级提示)
const camTs = ref(0)
const camFail = ref(false)
let camTimer = null
const camUrl = computed(() => `/api/printers/${id.value}/camera?ts=${camTs.value}`)
function refreshCam() {
  camFail.value = false
  camTs.value = Date.now()
}

// 腔体灯
const lightOn = ref(null)
const lightBusy = ref(false)
async function loadLight() {
  try {
    const r = await api.get(`/api/printers/${id.value}/light`)
    lightOn.value = r.on
  } catch { lightOn.value = null }
}
async function toggleLight() {
  if (lightBusy.value || lightOn.value === null) return
  lightBusy.value = true
  try {
    await api.post(`/api/printers/${id.value}/light`, { on: !lightOn.value })
    lightOn.value = !lightOn.value
    refreshCam()
  } catch (e) {
    showFailToast(e.message)
  } finally {
    lightBusy.value = false
  }
}

// 测试连通
const testing = ref(false)
async function test() {
  testing.value = true
  try {
    const t = await api.post(`/api/printers/${id.value}/test`)
    showSuccessToast(`连通:${t.state} 喷嘴 ${t.nozzle_temp ?? '?'}℃`)
  } catch (e) {
    showFailToast(`不通:${e.message}`)
  } finally {
    testing.value = false
  }
}

// CFS 料道(含手工库存)
async function loadCfs() {
  try { cfsInfo.value = await api.get(`/api/printers/${id.value}/cfs`) }
  catch { cfsInfo.value = null }
}
const cfsSlots = computed(() => {
  const out = []
  for (const b of cfsInfo.value?.boxes || [])
    (b.slots || []).forEach((s, i) => {
      if (s.color) out.push({ ...s, index: s.index || i + 1, box: b.box })
    })
  return out
})

onMounted(async () => {
  store.connect()
  try {
    const [ps, pr] = await Promise.all([api.get('/api/printers'), api.get('/api/profiles')])
    printers.value = ps
    profiles.value = pr
  } catch (e) {
    showFailToast(e.message)
  }
  loadCfs()
  loadLight()
  refreshCam()
  camTimer = setInterval(() => { camTs.value = Date.now() }, 5000)
})
onUnmounted(() => clearInterval(camTimer))
</script>

<template>
  <div class="pb-page" v-if="p">
    <van-nav-bar :title="p.name" left-arrow @click-left="router.back()" />

    <!-- 主视觉:摄像头画面 + 悬浮状态与灯光控制 -->
    <div class="pd-hero">
      <img v-if="!camFail" :src="camUrl" @error="camFail = true" />
      <div v-else class="pd-hero-ph">
        <van-icon name="video-o" size="34" />
        <div class="pb-muted" style="font-size:12px;margin-top:6px">摄像头不可用(私有协议或未配置)</div>
      </div>
      <div class="pd-hero-top">
        <van-tag :color="stateColor[tel?.state] || '#969799'" size="large">
          {{ stateText[tel?.state] || tel?.state || '未连接' }}
        </van-tag>
        <van-tag v-if="tel?.cfs_connected" color="#ff976a" size="large">CFS</van-tag>
      </div>
      <div class="pd-hero-actions">
        <button v-if="lightOn !== null" class="pd-hero-btn" @click="toggleLight">
          {{ lightOn ? '💡 关灯' : '💡 开灯' }}
        </button>
        <button class="pd-hero-btn" @click="refreshCam">🔄 刷新</button>
      </div>
    </div>

    <!-- 打印状态 + 温度 + 控制 -->
    <div class="pd-stats">
      <div class="pd-stat">
        <div class="pd-stat-label">喷嘴</div>
        <div class="pd-stat-value">{{ tel?.nozzle_temp ?? '-' }}<small> / {{ tel?.nozzle_target || 0 }}°</small></div>
      </div>
      <div class="pd-stat">
        <div class="pd-stat-label">热床</div>
        <div class="pd-stat-value">{{ tel?.bed_temp ?? '-' }}<small> / {{ tel?.bed_target || 0 }}°</small></div>
      </div>
      <div class="pd-stat">
        <div class="pd-stat-label">进度</div>
        <div class="pd-stat-value">{{ Math.round((tel?.progress || 0) * 100) }}<small> %</small></div>
      </div>
    </div>

    <div class="pb-card" v-if="tel?.filename">
      <div class="pb-row">
        <span class="pb-grow pb-ellipsis" style="font-weight:600">{{ tel.filename }}</span>
        <span class="pb-muted">{{ Math.round((tel.progress || 0) * 100) }}%</span>
      </div>
      <van-progress :percentage="Math.round((tel.progress || 0) * 100)" style="margin-top:6px" />
    </div>

    <div class="pb-row pd-controls">
      <van-button size="small" round plain :disabled="!canPause" @click="control('pause')">暂停</van-button>
      <van-button size="small" round plain type="primary" :disabled="!canResume" @click="control('resume')">恢复</van-button>
      <van-button size="small" round plain type="danger" :disabled="!canStop" @click="control('stop')">停止</van-button>
      <span class="pb-grow"></span>
      <van-button size="small" round plain :loading="testing" @click="test">测试连通</van-button>
    </div>

    <!-- CFS 料道 -->
    <div class="pb-card" v-if="cfsSlots.length">
      <h3 class="pd-title">CFS 料道</h3>
      <div class="pb-row" style="gap:14px;flex-wrap:wrap">
        <div v-for="s in cfsSlots" :key="s.box + s.slot"
             style="display:flex;flex-direction:column;align-items:center;gap:3px">
          <span class="pd-dot" :style="{ background: s.color }">
            <span class="pd-slotnum">{{ s.box.replace('T', '') }}{{ 'ABCD'[s.index - 1] || s.index }}</span>
          </span>
          <span class="pb-muted" style="font-size:10px">{{ s.material || '已装料' }}</span>
          <span class="pb-muted" style="font-size:10px">
            {{ s.grams != null ? s.grams + 'g' : '未记库存' }}
          </span>
        </div>
      </div>
    </div>

    <!-- 信息 -->
    <div class="pb-card">
      <h3 class="pd-title">信息</h3>
      <van-cell title="适配协议" :value="p.adapter" />
      <van-cell title="地址" :value="`${p.host}:${p.port || '默认'}`" />
      <van-cell title="机型参数包" :value="modelName" />
    </div>
  </div>
  <van-loading v-else center style="margin-top:40%">加载中...</van-loading>
</template>

<style scoped>
.pd-hero {
  position: relative; border-radius: 12px; overflow: hidden;
  background: linear-gradient(135deg, #eef2f7, #e4e9f2); margin-bottom: 10px;
}
.pd-hero img { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }
.pd-hero-ph {
  aspect-ratio: 16/9; display: flex; flex-direction: column;
  align-items: center; justify-content: center; color: #c8c9cc;
}
.pd-hero-top { position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; }
.pd-hero-actions { position: absolute; top: 10px; right: 10px; display: flex; gap: 6px; }
.pd-hero-btn {
  border: none; border-radius: 14px; padding: 4px 10px; font-size: 12px;
  background: rgba(255, 255, 255, .85); backdrop-filter: blur(4px);
  box-shadow: 0 1px 4px rgba(0, 0, 0, .15); cursor: pointer;
}
.pd-stats { display: flex; gap: 10px; margin-bottom: 10px; }
.pd-stat {
  flex: 1; background: #fff; border-radius: 12px; padding: 10px 12px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, .04);
}
.pd-stat-label { font-size: 11px; color: #969799; }
.pd-stat-value { font-size: 20px; font-weight: 700; color: #323233; margin-top: 2px; }
.pd-stat-value small { font-size: 12px; font-weight: 400; color: #969799; }
.pd-controls { margin-bottom: 10px; }
.pd-title { margin: 0 0 8px; font-size: 14px; }
.pd-dot {
  width: 26px; height: 26px; border-radius: 50%;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0;
  display: inline-flex; align-items: center; justify-content: center;
}
.pd-slotnum { font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; font-weight: 700; }
</style>
