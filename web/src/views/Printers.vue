<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Printer,
  Plus,
  Refresh,
  Search,
  Edit,
  Delete,
  VideoCamera,
  Setting,
  Connection,
  Check,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()

const printers = ref([])
const adapters = ref([])
const models = ref([])
const showForm = ref(false)
const editing = ref(null)

const thumbFail = reactive({})
const thumbTs = ref(Date.now())
const thumbUrl = (p) => `/api/printers/${p.id}/camera?ts=${thumbTs.value}`

const form = ref({
  name: '',
  adapter: 'creality_ws',
  host: '',
  port: null,
  secret: '',
  settings: { model: '', ssh_password: '' },
})

async function load() {
  try {
    printers.value = await api.get('/api/printers')
    adapters.value = await api.get('/api/printers/adapters')
    const pr = await api.get('/api/profiles')
    models.value = pr.map((b) => ({ key: b.key, name: b.name }))
  } catch (err) {
    // 忽略部分初始化错误
  }
}

// 局域网自动发现
const scanning = ref(false)
const scanHint = ref('')
const candidates = ref([])

async function scanLan() {
  scanning.value = true
  scanHint.value = '正在扫描局域网设备(约 5 秒)...'
  candidates.value = []
  try {
    const r = await api.post('/api/printers/discover', {})
    candidates.value = r.candidates || []
    scanHint.value = candidates.value.length
      ? `扫描完成，发现 ${candidates.value.length} 台设备，点击即可填入配置`
      : `未发现新设备，请确认设备已开机并在同一局域网`
  } catch (e) {
    scanHint.value = `扫描失败: ${e.message}`
  } finally {
    scanning.value = false
  }
}

function applyCandidate(c) {
  form.value.name = c.name
  form.value.adapter = c.adapter
  form.value.host = c.host
  form.value.port = c.port
  if (c.detail?.model) form.value.settings.model = c.detail.model
  else if (!form.value.settings.model && models.value.length) {
    form.value.settings.model = models.value[0].key
  }
}

function openAdd() {
  editing.value = null
  form.value = {
    name: '',
    adapter: 'creality_ws',
    host: '',
    port: null,
    secret: '',
    settings: { model: models.value[0]?.key || '', ssh_password: '' },
  }
  candidates.value = []
  scanHint.value = ''
  showForm.value = true
}

function openEdit(p) {
  editing.value = p.id
  form.value = {
    name: p.name,
    adapter: p.adapter,
    host: p.host,
    port: p.port,
    secret: p.secret || '',
    settings: {
      model: p.settings?.model || models.value[0]?.key || '',
      ssh_password: p.settings?.ssh_password || '',
    },
  }
  candidates.value = []
  scanHint.value = ''
  showForm.value = true
}

async function save() {
  const f = form.value
  if (!f.name.trim()) return ElMessage.warning('请填写打印机名称')
  if (!f.host.trim()) return ElMessage.warning('请填写打印机 IP 地址')

  const payload = {
    ...f,
    name: f.name.trim(),
    host: f.host.trim(),
    port: f.port === '' || f.port == null ? null : Number(f.port),
  }
  try {
    if (editing.value) {
      await api.put(`/api/printers/${editing.value}`, payload)
      ElMessage.success('打印机已更新')
    } else {
      await api.post('/api/printers', payload)
      ElMessage.success('打印机添加成功')
    }
    showForm.value = false
    load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
}

async function remove(p) {
  try {
    await ElMessageBox.confirm(`确定删除打印机 "${p.name}"？`, '删除确认', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.del(`/api/printers/${p.id}`)
    ElMessage.success('打印机已删除')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

const telOf = (p) => store.printers[p.id] || p.telemetry
const stateMap = {
  printing: { type: 'primary', text: '正在打印' },
  idle: { type: 'success', text: '空闲就绪' },
  paused: { type: 'warning', text: '已暂停' },
  error: { type: 'danger', text: '故障' },
  offline: { type: 'info', text: '离线' },
}

const onTel = () => {}
onMounted(() => {
  load()
  store.on(onTel)
})
onUnmounted(() => store.off(onTel))
</script>

<template>
  <div class="pb-page">
    <div class="printer-page-head">
      <div>
        <h1 class="page-title">3D 打印机集群与遥测</h1>
        <p class="page-subtitle">连接与管控创想 K 系列 (本地 WS) 与 Klipper / Moonraker 协议 3D 打印设备</p>
      </div>
      <div class="head-btn-group">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openAdd">添加打印机</el-button>
      </div>
    </div>

    <!-- 空白状态 -->
    <div v-if="!printers.length" class="empty-printer-box">
      <div class="empty-icon">🖨️</div>
      <h3>尚未连接任何打印机</h3>
      <p>点击上方「添加打印机」或通过局域网自动探测一键接入创想/Klipper 打印机</p>
      <el-button type="primary" :icon="Plus" @click="openAdd">立即添加首台设备</el-button>
    </div>

    <!-- 设备卡片网格 -->
    <div v-else class="printer-grid">
      <div
        v-for="p in printers"
        :key="p.id"
        class="printer-card"
        @click="router.push(`/printers/${p.id}`)"
      >
        <!-- 摄像头或预览占位 -->
        <div class="card-visual-frame">
          <img
            v-if="!thumbFail[p.id]"
            :src="thumbUrl(p)"
            alt="摄像头画面"
            class="cam-img"
            @error="thumbFail[p.id] = true"
          />
          <div v-else class="cam-ph">
            <el-icon :size="36"><Printer /></el-icon>
            <span style="font-size: 11px; margin-top: 4px;">无视频流 / 离线</span>
          </div>

          <div class="visual-tags-bar">
            <el-tag
              size="small"
              :type="stateMap[telOf(p)?.state]?.type || 'info'"
              effect="dark"
              class="state-tag"
            >
              {{ stateMap[telOf(p)?.state]?.text || telOf(p)?.state || '未连接' }}
            </el-tag>
            <el-tag v-if="telOf(p)?.cfs_connected" size="small" type="warning" effect="dark">
              CFS 多色
            </el-tag>
          </div>
        </div>

        <!-- 设备主信息 -->
        <div class="card-body">
          <div class="printer-title-bar">
            <div class="title-meta">
              <h3 class="p-name" :title="p.name">{{ p.name }}</h3>
              <div class="p-host">{{ p.adapter }} · {{ p.host }}{{ p.port ? `:${p.port}` : '' }}</div>
            </div>
            <div class="p-actions" @click.stop>
              <el-button link :icon="Edit" type="primary" @click="openEdit(p)" />
              <el-button link :icon="Delete" type="danger" @click="remove(p)" />
            </div>
          </div>

          <!-- 温度遥测双胶囊 -->
          <div class="temp-readings">
            <div class="temp-item nozzle">
              <span class="temp-label">🔥 喷嘴:</span>
              <span class="temp-val">{{ telOf(p)?.nozzle_temp ?? '-' }}℃</span>
              <span class="temp-target">/ {{ telOf(p)?.nozzle_target || 0 }}℃</span>
            </div>
            <div class="temp-item bed">
              <span class="temp-label">🛏️ 热床:</span>
              <span class="temp-val">{{ telOf(p)?.bed_temp ?? '-' }}℃</span>
              <span class="temp-target">/ {{ telOf(p)?.bed_target || 0 }}℃</span>
            </div>
          </div>

          <!-- 打印中任务与进度 -->
          <div v-if="telOf(p)?.progress" class="job-progress-block">
            <div class="progress-info">
              <span class="job-file-name" :title="telOf(p).filename">{{ telOf(p).filename || '打印任务中' }}</span>
              <span class="pct-text">{{ Math.round(telOf(p).progress * 100) }}%</span>
            </div>
            <el-progress :percentage="Math.round(telOf(p).progress * 100)" :stroke-width="6" />
          </div>

          <!-- 底部控制按钮 -->
          <div class="card-footer-btns">
            <el-button size="small" type="primary" plain style="width: 100%;">
              进入设备控制台 &gt;
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加/编辑打印机对话框 -->
    <el-dialog
      v-model="showForm"
      :title="editing ? '编辑打印机配置' : '添加 3D 打印机'"
      width="520px"
      destroy-on-close
    >
      <div class="dialog-body">
        <!-- 局域网探测功能 -->
        <div class="lan-scan-box">
          <div class="lan-scan-head">
            <span style="font-weight: 600; font-size: 13px;">局域网设备探测</span>
            <el-button size="small" type="primary" plain :loading="scanning" :icon="Search" @click="scanLan">
              一键扫描设备
            </el-button>
          </div>
          <div v-if="scanHint" class="scan-hint-text">{{ scanHint }}</div>
          <div v-if="candidates.length" class="candidates-list">
            <div
              v-for="c in candidates"
              :key="c.host + ':' + c.port"
              class="candidate-row"
              @click="applyCandidate(c)"
            >
              <div>
                <strong>{{ c.name }}</strong>
                <div class="text-sub">{{ c.host }}:{{ c.port }} · {{ c.adapter }}</div>
              </div>
              <el-button size="small" type="primary" link>填入</el-button>
            </div>
          </div>
        </div>

        <el-form label-position="top">
          <el-form-item label="设备名称" required>
            <el-input v-model="form.name" placeholder="如：创想 K2 Plus / 实验室 Voron 2.4" />
          </el-form-item>

          <div class="form-row-2">
            <el-form-item label="适配器协议" style="flex: 1;">
              <el-select v-model="form.adapter" style="width: 100%;">
                <el-option v-for="a in adapters" :key="a.key" :label="a.name" :value="a.key" />
              </el-select>
            </el-form-item>
            <el-form-item label="对应切片机型" style="flex: 1;">
              <el-select v-model="form.settings.model" style="width: 100%;">
                <el-option v-for="m in models" :key="m.key" :label="m.name" :value="m.key" />
              </el-select>
            </el-form-item>
          </div>

          <div class="form-row-2">
            <el-form-item label="IP 地址" required style="flex: 2;">
              <el-input v-model="form.host" placeholder="192.168.1.50" />
            </el-form-item>
            <el-form-item label="端口" style="flex: 1;">
              <el-input v-model="form.port" type="number" placeholder="默认" />
            </el-form-item>
          </div>

          <el-form-item label="访问密钥 (Secret)">
            <el-input v-model="form.secret" placeholder="Moonraker API Key / 创想 FTP 密码" />
          </el-form-item>

          <el-form-item label="SSH 密码 (选填)">
            <el-input v-model="form.settings.ssh_password" placeholder="选填: 读取 CFS 料道颜色 (只读)" />
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" @click="save">保存设备</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.printer-page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
}
.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}
.head-btn-group {
  display: flex;
  gap: 12px;
}

.empty-printer-box {
  text-align: center;
  padding: 60px 20px;
  background: #ffffff;
  border-radius: var(--pb-radius);
  border: 1px dashed #cbd5e1;
}
.empty-icon { font-size: 44px; margin-bottom: 12px; }

.printer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.printer-card {
  background: #ffffff;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.printer-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 20px -3px rgba(15, 23, 42, 0.08);
  border-color: #cbd5e1;
}

.card-visual-frame {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #0f172a;
  overflow: hidden;
}
.cam-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cam-ph {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #64748b;
  background: linear-gradient(135deg, #1e293b, #0f172a);
}

.visual-tags-bar {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  gap: 6px;
}

.card-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

.printer-title-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.title-meta {
  flex: 1;
  min-width: 0;
}
.p-name {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.p-host {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
  font-family: monospace;
}
.p-actions {
  display: flex;
  gap: 2px;
}

.temp-readings {
  display: flex;
  gap: 8px;
}
.temp-item {
  flex: 1;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.temp-item.nozzle {
  background: #fef2f2;
  color: #991b1b;
}
.temp-item.bed {
  background: #eff6ff;
  color: #1e40af;
}
.temp-val { font-weight: 700; }
.temp-target { color: #94a3b8; font-size: 11px; }

.job-progress-block {
  background: #f8fafc;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}
.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 6px;
}
.job-file-name {
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.pct-text {
  font-weight: 700;
  color: #2563eb;
}

.card-footer-btns {
  margin-top: auto;
  padding-top: 4px;
}

/* 探测与表单样式 */
.lan-scan-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}
.lan-scan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.scan-hint-text {
  font-size: 12px;
  color: #64748b;
  margin-top: 6px;
}
.candidates-list {
  margin-top: 8px;
  border-top: 1px solid #e2e8f0;
  padding-top: 6px;
  max-height: 140px;
  overflow: auto;
}
.candidate-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.candidate-row:hover { background: #edf2f7; }
.text-sub { font-size: 11px; color: #64748b; font-family: monospace; }
.form-row-2 {
  display: flex;
  gap: 12px;
}
</style>
