<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
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

// 摄像头快照(5 秒自动刷新,失败降级提示)
const camTs = ref(0)
const camFail = ref(false)
let camTimer = null
const camUrl = computed(() => `/api/printers/${id.value}/camera?ts=${camTs.value}`)
function refreshCam() {
  camFail.value = false
  camTs.value = Date.now()
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
  refreshCam()
  camTimer = setInterval(() => { camTs.value = Date.now() }, 5000)
})
onUnmounted(() => clearInterval(camTimer))
</script>

<template>
  <div class="pb-page" v-if="p">
    <van-nav-bar :title="p.name" left-arrow @click-left="router.back()" />

    <div class="pb-grid" style="grid-template-columns:1fr">
      <!-- 状态与控制 -->
      <div class="pb-card">
        <div class="pb-row">
          <van-tag :color="stateColor[tel?.state] || '#969799'" size="large">
            {{ stateText[tel?.state] || tel?.state || '未连接' }}
          </van-tag>
          <span class="pb-grow"></span>
          <span v-if="tel?.cfs_connected" color="#ff976a">
            <van-tag color="#ff976a">CFS 在线</van-tag></span>
        </div>
        <div class="pb-row" style="margin-top:10px;gap:16px;flex-wrap:wrap">
          <span class="pb-muted">喷嘴 {{ tel?.nozzle_temp ?? '-' }} / {{ tel?.nozzle_target ?? '-' }}℃</span>
          <span class="pb-muted">热床 {{ tel?.bed_temp ?? '-' }} / {{ tel?.bed_target ?? '-' }}℃</span>
        </div>
        <template v-if="tel?.filename">
          <div class="pb-ellipsis" style="margin-top:8px;font-weight:600">{{ tel.filename }}</div>
          <van-progress :percentage="Math.round((tel.progress || 0) * 100)" style="margin-top:6px" />
          <div class="pb-muted" style="margin-top:4px">{{ Math.round((tel.progress || 0) * 100) }}%</div>
        </template>
        <div class="pb-row" style="margin-top:12px">
          <van-button size="small" plain @click="control('pause')">暂停</van-button>
          <van-button size="small" plain @click="control('resume')">恢复</van-button>
          <van-button size="small" plain type="danger" @click="control('stop')">停止</van-button>
        </div>
      </div>

      <!-- 摄像头快照 -->
      <div class="pb-card">
        <div class="pb-row">
          <h3 class="pb-title pb-grow" style="margin:0">摄像头</h3>
          <van-button size="mini" plain @click="refreshCam">刷新</van-button>
        </div>
        <img v-if="!camFail" :src="camUrl" @error="camFail = true"
             style="width:100%;border-radius:8px;background:#f7f8fa;min-height:100px;margin-top:8px" />
        <div v-else class="pb-muted" style="background:#f7f8fa;border-radius:8px;padding:14px;text-align:center;margin-top:8px">
          摄像头快照不可用:该机型可能使用私有视频协议(如创想 K 系列本地 WebRTC),
          或未在 Moonraker 中配置 webcam
        </div>
      </div>

      <!-- CFS 料道 -->
      <div class="pb-card" v-if="cfsSlots.length">
        <h3 class="pb-title" style="margin:0 0 8px">CFS 料道</h3>
        <div class="pb-row" style="gap:14px;flex-wrap:wrap">
          <div v-for="s in cfsSlots" :key="s.box + s.slot"
               style="display:flex;flex-direction:column;align-items:center;gap:3px">
            <span class="pb-dot" :style="{ background: s.color }">
              <span class="pb-slotnum">{{ s.box.replace('T', '') }}{{ 'ABCD'[s.index - 1] || s.index }}</span>
            </span>
            <span class="pb-muted" style="font-size:10px">{{ s.material || '已装料' }}</span>
            <span class="pb-muted" style="font-size:10px">
              {{ s.grams != null ? s.grams + 'g' : '未记库存' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 打印机信息 -->
      <div class="pb-card">
        <h3 class="pb-title" style="margin:0 0 8px">信息</h3>
        <van-cell title="适配协议" :value="p.adapter" />
        <van-cell title="地址" :value="`${p.host}:${p.port || '默认'}`" />
        <van-cell title="机型参数包" :value="modelName" />
      </div>
    </div>
  </div>
  <van-loading v-else center style="margin-top:40%">加载中...</van-loading>
</template>

<style scoped>
.pb-dot {
  width: 26px; height: 26px; border-radius: 50%;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0;
  display: inline-flex; align-items: center; justify-content: center;
}
.pb-slotnum { font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; font-weight: 700; }
</style>
