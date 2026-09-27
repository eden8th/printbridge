<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const printers = ref([])
const adapters = ref([])
const showForm = ref(false)
const testing = ref(false)
const editing = ref(null)

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
}

async function load() {
  printers.value = await api.get('/api/printers')
  adapters.value = await api.get('/api/printers/adapters')
}

function openAdd() {
  editing.value = null
  form.value = { name: '', adapter: 'creality_ws', host: '', port: null, secret: '', settings: {} }
  showForm.value = true
}

function openEdit(p) {
  editing.value = p.id
  form.value = {
    name: p.name, adapter: p.adapter, host: p.host, port: p.port,
    secret: p.secret || '', settings: p.settings || {},
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

async function test(p) {
  testing.value = true
  try {
    const tel = await api.post(`/api/printers/${p.id}/test`)
    showSuccessToast(`连通:${tel.state} 喷嘴 ${tel.nozzle_temp ?? '?'}℃`)
    load()
  } catch (e) {
    showFailToast(`不通:${e.message}`)
  } finally {
    testing.value = false
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

    <div v-for="p in printers" :key="p.id" class="pb-card">
      <div class="pb-row">
        <div class="pb-grow">
          <div style="font-weight:600">
            {{ p.name }}
            <span class="pb-muted" style="font-weight:400">{{ p.adapter }} · {{ p.host }}</span>
          </div>
        </div>
        <van-tag :color="stateColor[telOf(p)?.state] || '#969799'">
          {{ telOf(p)?.state || '未连接' }}
        </van-tag>
        <van-tag v-if="telOf(p)?.cfs_connected" color="#ff976a">CFS</van-tag>
      </div>

      <div v-if="telOf(p)" class="pb-row" style="margin-top:8px;gap:16px;flex-wrap:wrap">
        <span class="pb-muted">喷嘴 {{ telOf(p).nozzle_temp ?? '-' }} /
          {{ telOf(p).nozzle_target ?? '-' }}℃</span>
        <span class="pb-muted">热床 {{ telOf(p).bed_temp ?? '-' }} /
          {{ telOf(p).bed_target ?? '-' }}℃</span>
        <span v-if="telOf(p).progress != null" class="pb-muted">
          {{ Math.round(telOf(p).progress * 100) }}%</span>
        <span v-if="telOf(p).filename" class="pb-muted pb-ellipsis">
          {{ telOf(p).filename }}</span>
      </div>

      <van-progress v-if="telOf(p)?.progress != null" :percentage="Math.round(telOf(p).progress * 100)"
                    style="margin-top:6px" />

      <div class="pb-row" style="margin-top:10px">
        <van-button size="small" plain type="primary" :loading="testing" @click="test(p)">测试</van-button>
        <van-button size="small" plain @click="openEdit(p)">编辑</van-button>
        <van-button size="small" plain @click="control(p, 'pause')">暂停</van-button>
        <van-button size="small" plain @click="control(p, 'resume')">恢复</van-button>
        <van-button size="small" plain type="danger" @click="control(p, 'stop')">停止</van-button>
        <span class="pb-grow"></span>
        <van-icon name="delete-o" color="#969799" @click="remove(p)" />
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
      <van-field v-model="form.host" label="IP 地址" placeholder="192.168.1.50" />
      <van-field v-model="form.port" type="number" label="端口" placeholder="留空用默认端口" />
      <van-field v-model="form.secret" label="密钥" placeholder="Moonraker API Key / FTP 密码" />
      <div class="pb-muted" style="padding:4px 16px 10px">
        创想 K 系列默认端口 9999;Klipper/Moonraker 默认 7125。连不上时先在电脑上跑探测工具。
      </div>
    </van-dialog>
  </div>
</template>

<style scoped>
.pb-select { width: 100%; border: 1px solid #ebedf0; border-radius: 6px; padding: 4px 8px; }
</style>
