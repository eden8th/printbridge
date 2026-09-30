<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()

const printers = ref([])
const adapters = ref([])
const models = ref([])     // 可选机型(= 切片参数包列表)
const showForm = ref(false)
const editing = ref(null)

// 卡片缩略图:进页面时拍一帧(不轮询,保持列表轻量);失败显示占位
const thumbFail = reactive({})
const thumbTs = ref(Date.now())
const thumbUrl = (p) => `/api/printers/${p.id}/camera?ts=${thumbTs.value}`

const form = ref({
  name: '', adapter: 'creality_ws', host: '', port: null, secret: '',
  settings: {},
})

// 局域网自动发现
const scanning = ref(false)
const scanHint = ref('')
const candidates = ref([])

async function scanLan() {
  scanning.value = true
  scanHint.value = '正在扫描(约 5 秒)...'
  candidates.value = []
  try {
    const r = await api.post('/api/printers/discover', {})
    candidates.value = r.candidates || []
    scanHint.value = candidates.value.length
      ? `扫描完成,发现 ${candidates.value.length} 台设备,点击填入`
      : `未发现设备(已扫描 ${(r.scanned || []).join('、')}),可手动填写`
  } catch (e) {
    scanHint.value = `扫描失败:${e.message}`
  } finally {
    scanning.value = false
  }
}

function applyCandidate(c) {
  form.value.name = c.name
  form.value.adapter = c.adapter
  form.value.host = c.host
  form.value.port = c.port
  // 发现时按主机名匹配到的机型(如 K2Pro-29BB → Creality K2 Pro)
  if (c.detail?.model) form.value.settings.model = c.detail.model
  else if (!form.value.settings.model && models.value.length)
    form.value.settings.model = models.value[0].key
}

async function load() {
  printers.value = await api.get('/api/printers')
  adapters.value = await api.get('/api/printers/adapters')
  try {
    const pr = await api.get('/api/profiles')
    models.value = pr.map((b) => ({ key: b.key, name: b.name }))
  } catch { models.value = [] }
}

function openAdd() {
  editing.value = null
  form.value = {
    name: '', adapter: 'creality_ws', host: '', port: null, secret: '',
    settings: { model: models.value[0]?.key || '', ssh_password: '' },
  }
  showForm.value = true
}

function openEdit(p) {
  editing.value = p.id
  form.value = {
    name: p.name, adapter: p.adapter, host: p.host, port: p.port,
    secret: p.secret || '',
    settings: {
      model: p.settings?.model || models.value[0]?.key || '',
      ssh_password: p.settings?.ssh_password || '',
    },
  }
  showForm.value = true
}

async function save() {
  const f = form.value
  if (!f.name.trim()) return showFailToast('请填写打印机名称')
  if (!f.host.trim()) return showFailToast('请填写打印机 IP 地址')
  // Vant number 输入框返回字符串:空→null,数字→int
  const payload = {
    ...f,
    name: f.name.trim(),
    host: f.host.trim(),
    port: f.port === '' || f.port == null ? null : Number(f.port),
  }
  if (payload.port != null && Number.isNaN(payload.port)) {
    return showFailToast('端口必须是数字')
  }
  try {
    if (editing.value) await api.put(`/api/printers/${editing.value}`, payload)
    else await api.post('/api/printers', payload)
    showForm.value = false
    showSuccessToast('已保存')
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

async function remove(p) {
  await api.del(`/api/printers/${p.id}`)
  load()
}

async function control(p, action) {
  try {
    await api.post(`/api/printers/${p.id}/control`, { action })
    showSuccessToast(`已发送 ${action}`)
  } catch (e) {
    showFailToast(e.message)
  }
}

const telOf = (p) => store.printers[p.id] || p.telemetry
const stateColor = { printing: '#07c160', idle: '#1989fa', paused: '#ff976a', error: '#ee0a24', offline: '#969799' }
const stateText = { printing: '打印中', idle: '空闲', paused: '已暂停', error: '故障', offline: '离线' }

const onTel = () => { /* store.printers 本身响应式,无需处理 */ }
onMounted(() => { load(); store.on(onTel) })
onUnmounted(() => store.off(onTel))
</script>

<template>
  <div class="pb-page">
    <van-nav-bar title="打印机">
      <template #right>
        <span class="pb-navbar-action" role="button" @click="openAdd">添加</span>
      </template>
    </van-nav-bar>

    <van-empty v-if="!printers.length" description="还没有打印机,点右上角添加" />

    <div class="pb-grid">
      <div v-for="p in printers" :key="p.id" class="pb-card clickable pc-card"
           @click="router.push(`/printers/${p.id}`)">
        <!-- 主视觉:摄像头快照(加载失败退化为渐变占位) -->
        <div class="pc-visual" @click.stop="router.push(`/printers/${p.id}`)">
          <img v-if="!thumbFail[p.id]" :src="thumbUrl(p)" @error="thumbFail[p.id] = true" />
          <div v-else class="pc-visual-ph">
            <van-icon name="printer" size="30" />
          </div>
          <div class="pc-visual-tags">
            <van-tag :color="stateColor[telOf(p)?.state] || '#969799'">
              {{ stateText[telOf(p)?.state] || telOf(p)?.state || '未连接' }}
            </van-tag>
            <van-tag v-if="telOf(p)?.cfs_connected" color="#ff976a">CFS</van-tag>
          </div>
        </div>

        <div class="pb-row" style="margin-top:10px;padding:0 12px">
          <div class="pb-grow pb-ellipsis">
            <div style="font-weight:600">{{ p.name }}</div>
            <div class="pb-muted" style="font-size:12px;margin-top:2px">
              {{ p.adapter }} · {{ p.host }}
            </div>
          </div>
          <van-icon name="edit" color="#1989fa" size="18"
                    style="margin-right:10px" @click.stop="openEdit(p)" />
          <van-icon name="delete-o" color="#969799" size="18" @click.stop="remove(p)" />
        </div>

        <div class="pb-row pc-stats" style="margin-top:8px">
          <span class="pc-stat">喷嘴 <b>{{ telOf(p)?.nozzle_temp ?? '-' }}</b>/{{
            telOf(p)?.nozzle_target || 0 }}°</span>
          <span class="pc-stat">热床 <b>{{ telOf(p)?.bed_temp ?? '-' }}</b>/{{
            telOf(p)?.bed_target || 0 }}°</span>
          <span v-if="telOf(p)?.progress" class="pc-stat pb-grow pb-ellipsis">
            {{ telOf(p).filename }}</span>
        </div>
        <van-progress v-if="telOf(p)?.progress" :percentage="Math.round(telOf(p).progress * 100)"
                      style="margin:8px 12px 0" />
      </div>
    </div>

    <van-dialog v-model:show="showForm" :title="editing ? '编辑打印机' : '添加打印机'"
                show-cancel-button @confirm="save" style="padding:8px">
      <div style="padding:0 4px">
        <van-button size="small" type="primary" plain :loading="scanning"
                    style="margin-bottom:8px" @click="scanLan">
          扫描局域网
        </van-button>
        <div v-if="candidates.length" class="pb-scan-list">
          <van-cell v-for="(c, i) in candidates" :key="c.host + ':' + c.port" clickable
                    center @click="applyCandidate(c)">
            <template #title>
              <span style="font-weight:600">{{ c.name }}</span>
            </template>
            <template #label>
              {{ c.host }}:{{ c.port }} · {{ c.adapter }}
              <span v-if="c.detail?.alt_adapters?.length" class="pb-muted">
                (也支持 {{ c.detail.alt_adapters.join('/') }})</span>
            </template>
            <template #right-icon>
              <van-icon name="arrow" color="#c8c9cc" />
            </template>
          </van-cell>
        </div>
        <div v-if="scanHint" class="pb-muted" style="padding:0 4px 6px">{{ scanHint }}</div>
      </div>
      <van-field v-model="form.name" label="名称" placeholder="客厅 K2 Plus" />
      <van-field label="适配器" readonly>
        <template #input>
          <select v-model="form.adapter" class="pb-select">
            <option v-for="a in adapters" :key="a.key" :value="a.key">{{ a.name }}</option>
          </select>
        </template>
      </van-field>
      <van-field label="机型" readonly>
        <template #input>
          <select v-model="form.settings.model" class="pb-select">
            <option v-for="m in models" :key="m.key" :value="m.key">{{ m.name }}</option>
          </select>
        </template>
      </van-field>
      <van-field v-model="form.host" label="IP 地址" placeholder="192.168.1.50" />
      <van-field v-model="form.port" type="number" label="端口" placeholder="留空用默认端口" />
      <van-field v-model="form.secret" label="密钥" placeholder="Moonraker API Key / FTP 密码" />
      <van-field v-model="form.settings.ssh_password" label="SSH 密码"
                 placeholder="选填:读取 CFS 料道颜色(只读)" />
      <div class="pb-muted" style="padding:4px 16px 10px">
        创想 K 系列默认端口 9999;Klipper/Moonraker 默认 7125。连不上时先在电脑上跑探测工具。
      </div>
    </van-dialog>
  </div>
</template>

<style scoped>
.pb-select { width: 100%; border: 1px solid #ebedf0; border-radius: 6px; padding: 4px 8px; }
.pc-card { padding: 0 0 12px; overflow: hidden; }
.pc-visual { position: relative; background: linear-gradient(135deg, #eef2f7, #e4e9f2); }
.pc-visual img { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }
.pc-visual-ph {
  aspect-ratio: 16/9; display: flex; align-items: center; justify-content: center;
  color: #c8c9cc;
}
.pc-visual-tags { position: absolute; top: 8px; left: 8px; display: flex; gap: 6px; }
.pc-stats { gap: 12px; font-size: 12px; color: #969799; padding: 0 12px; }
.pc-stat b { font-weight: 600; color: #323233; }
</style>
