<script setup>
import { watch, computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api, uploadFile } from '../api'
import { store } from '../store'
import { useIsMobile } from '../composables/useDevice'
import PrintConfigPopup from '../components/PrintConfigPopup.vue'

const router = useRouter()
const isMobile = useIsMobile()

const models = ref([])
const batchMode = ref(false)
const selected = ref(new Set())
const showLinkImport = ref(false)
const shareUrl = ref('')

// 切片打印配置弹层(3MF/STL 模型文件)
const showPrint = ref(false)
const printFile = ref(null)
const printPayload = computed(() =>
  printFile.value ? { model_file_id: printFile.value.id } : {})

function openPrint(f) {
  printFile.value = f
  showPrint.value = true
}

// G-code 推送打印(跳过切片,直接上传启动)
const showPush = ref(false)
const pushFile = ref(null)
const pushPrinters = ref([])
const pushPrinterId = ref(null)
const pushCfs = ref('')
const pushAuto = ref(true)
const pushSlots = ref([])

async function openPush(f) {
  pushFile.value = f
  pushCfs.value = ''
  pushSlots.value = []
  if (!pushPrinters.value.length) {
    try { pushPrinters.value = await api.get('/api/printers') } catch { /* 提交时校验 */ }
  }
  showPush.value = true
}

// 选打印机 → 拉 CFS 料道(可选换料)
watch(pushPrinterId, async () => {
  pushSlots.value = []
  pushCfs.value = ''
  if (!pushPrinterId.value) return
  try {
    const info = await api.get(`/api/printers/${pushPrinterId.value}/cfs`)
    for (const b of info?.boxes || [])
      (b.slots || []).forEach((s) => {
        if (s.color) pushSlots.value.push({
          tnn: s.slot, label: `${s.slot} · ${s.material || '已装料'}`, color: s.color,
        })
      })
  } catch { /* 无 CFS 时无选项 */ }
})

async function submitPush() {
  if (!pushPrinterId.value) return showFailToast('请选择打印机')
  try {
    const r = await api.post('/api/jobs/print-gcode', {
      file_id: pushFile.value.id,
      printer_id: pushPrinterId.value,
      cfs_tnn: pushCfs.value || null,
      auto_start: pushAuto.value,
    })
    showPush.value = false
    showSuccessToast(`任务 #${r.job_id} 已提交`)
    router.push('/jobs')
  } catch (e) {
    showFailToast(e.message)
  }
}

function onSubmitted(res) {
  showSuccessToast(`任务 #${res.job_id} 已提交`)
  router.push('/jobs')
}

async function importFromLink() {
  const url = shareUrl.value.trim()
  if (!url) return
  try {
    const r = await api.post('/api/sources/parse-link', { url })
    showLinkImport.value = false
    shareUrl.value = ''
    if (r.region_switched) {
      showSuccessToast(`已按链接切换到拓竹${r.region === 'com' ? '国际站' : '国内站'}源`)
    } else if (r.localized) {
      showSuccessToast('已匹配到该模型在国内站的条目,标题与描述已中文化')
    } else if (r.overseas_only) {
      showSuccessToast('该模型未同步到国内站,按国际站原文展示')
    }
    // 跳转模型详情页(可选版本后一键打印/入库)
    router.push(`/model/${r.source}/${r.design_id}`)
  } catch (e) {
    showFailToast(e.message)
  }
}

async function load() {
  try {
    models.value = await api.get('/api/library')
  } catch (e) {
    showFailToast(e.message)
  }
}

function toggleBatch() {
  batchMode.value = !batchMode.value
  selected.value = new Set()
}

function toggleSelect(m) {
  const s = new Set(selected.value)
  if (s.has(m.id)) s.delete(m.id)
  else s.add(m.id)
  selected.value = s
}

const allSelected = computed(() =>
  models.value.length > 0 && models.value.every((m) => selected.value.has(m.id)))

function toggleAll() {
  selected.value = new Set(allSelected.value ? [] : models.value.map((m) => m.id))
}

async function batchDelete() {
  if (!selected.value.size) return
  try {
    await showConfirmDialog({
      title: '批量删除',
      message: `确定删除所选 ${selected.value.size} 个模型?关联的模型文件将一并删除。`,
    })
  } catch { return }
  try {
    const r = await api.post('/api/library/batch-delete', { ids: [...selected.value] })
    showSuccessToast(`已删除 ${r.deleted} 个`)
    batchMode.value = false
    selected.value = new Set()
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

async function onUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    await uploadFile(file)
    showSuccessToast('已上传')
    load()
  } catch (err) {
    showFailToast(err.message)
  }
}

function del(m) {
  showConfirmDialog({ title: '删除模型', message: `确定删除「${m.title}」?` })
    .then(async () => {
      await api.del(`/api/library/${m.id}`)
      load()
    }).catch(() => {})
}

// 来源模型(MakerWorld 等)可跳详情页选版本后一键打印;
// 本地上传(source=upload)/切片产物(source=sliced)没有线上设计页
function canOpen(m) {
  return !!m.source_design_id && /^\d+$/.test(String(m.source_design_id))
    && !['upload', 'sliced'].includes(m.source)
}

function openModel(m) {
  if (batchMode.value) { toggleSelect(m); return }
  if (canOpen(m)) {
    router.push(`/model/${m.source}/${m.source_design_id}`)
  } else if (m.source === 'upload') {
    showFailToast('本地上传的模型暂不支持详情页,请通过任务页切片打印')
  }
}

function fmtSize(n) {
  if (!n) return ''
  if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${Math.round(n / 1024)} KB`
}

const onLib = () => load()
onMounted(() => { load(); store.on(onLib) })
onUnmounted(() => store.off(onLib))
</script>

<template>
  <div class="pb-page">
    <van-nav-bar title="我的模型库">
      <template #right>
        <span class="pb-navbar-action" role="button" @click="showLinkImport = true">
          {{ isMobile ? '导入' : '链接导入' }}
        </span>
        <span class="pb-navbar-action" role="button"
              @click="models.length && toggleBatch()">
          {{ batchMode ? '退出' : (isMobile ? '管理' : '批量管理') }}
        </span>
        <label class="pb-navbar-action" role="button" style="margin-left:10px">
          <input type="file" accept=".3mf,.stl,.gcode" style="display:none" @change="onUpload" />
          上传
        </label>
      </template>
    </van-nav-bar>

    <van-empty v-if="!models.length" description="还没有模型,去「发现」页搜索,或点右上角上传" />

    <div class="pb-grid">
      <div v-for="m in models" :key="m.id" class="pb-card clickable"
           @click="openModel(m)">
        <div class="pb-row">
          <van-checkbox v-if="batchMode" :model-value="selected.has(m.id)"
                        checked-color="#1989fa" style="margin-right:4px"
                        @click.stop @update:model-value="toggleSelect(m)" />
          <img v-if="m.cover" class="pb-thumb" :src="m.cover" loading="lazy" />
          <div class="pb-grow">
            <div style="font-weight:600" class="pb-ellipsis">{{ m.title }}</div>
            <div class="pb-muted pb-ellipsis" style="margin-top:4px">
              {{ m.source }} · @{{ m.author || '-' }}
            </div>
          </div>
          <van-icon v-if="!batchMode && canOpen(m)" name="arrow" color="#969799" size="18" />
          <van-icon v-if="!batchMode" name="delete-o" color="#ee0a24" size="20" @click="del(m)" />
        </div>
        <div v-for="f in m.files" :key="f.id"
             class="pb-row" style="margin-top:8px;background:#f7f8fa;border-radius:8px;padding:8px">
          <van-icon name="description" size="18" />
          <div class="pb-grow pb-ellipsis pb-muted">{{ f.name }} · {{ fmtSize(f.size) }}</div>
          <template v-if="!batchMode">
            <van-button v-if="['3mf', 'stl'].includes(f.kind)" size="mini" plain type="primary"
                        style="margin-right:6px" @click.stop="openPrint(f)">打印</van-button>
            <van-button v-else-if="f.kind === 'gcode'" size="mini" plain type="primary"
                        style="margin-right:6px" @click.stop="openPush(f)">推送打印</van-button>
            <a :href="`/api/library/files/${f.id}/download`">
              <van-button size="mini" plain>下载</van-button>
            </a>
          </template>
        </div>
      </div>
    </div>

    <!-- 模型文件打印配置(共用弹层) -->
    <PrintConfigPopup v-model:show="showPrint" title="切片并打印"
                      :base-payload="printPayload" @submitted="onSubmitted" />

    <!-- G-code 推送打印 -->
    <van-popup v-model:show="showPush" position="bottom" round style="padding:16px">
      <h3 class="pb-title">推送打印</h3>
      <div class="pb-muted" style="padding:0 0 6px">
        {{ pushFile?.name }} · 已是 G-code,跳过切片直接上传
      </div>
      <van-field label="打印机" readonly>
        <template #input>
          <select v-model="pushPrinterId" class="pb-select">
            <option :value="null" disabled>请选择</option>
            <option v-for="p in pushPrinters" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </template>
      </van-field>
      <van-field v-if="pushSlots.length" label="CFS 料道" readonly>
        <template #input>
          <select v-model="pushCfs" class="pb-select">
            <option value="">不换料</option>
            <option v-for="s in pushSlots" :key="s.tnn" :value="s.tnn">{{ s.label }}</option>
          </select>
        </template>
      </van-field>
      <van-cell title="上传后自动开始打印">
        <template #right-icon>
          <van-switch v-model="pushAuto" size="22" />
        </template>
      </van-cell>
      <van-button type="primary" block round style="margin-top:10px"
                  :disabled="!pushPrinterId" @click="submitPush">开始打印</van-button>
    </van-popup>

    <!-- 批量操作栏 -->
    <div v-if="batchMode && models.length" class="pb-batchbar">
      <van-checkbox :model-value="allSelected" checked-color="#1989fa"
                    @update:model-value="toggleAll">全选</van-checkbox>
      <van-button type="danger" size="small" round :disabled="!selected.size"
                  @click="batchDelete">
        删除所选({{ selected.size }})
      </van-button>
    </div>

    <!-- 分享链接导入 -->
    <van-dialog v-model:show="showLinkImport" title="分享链接导入" show-cancel-button
                @confirm="importFromLink">
      <van-field v-model="shareUrl" label="链接" type="textarea" rows="2" autosize
                 placeholder="粘贴拓竹分享链接,如 https://makerworld.com/zh/models/123456" />
      <div class="pb-muted" style="padding:4px 16px 10px">
        支持拓竹 MakerWorld 分享链接(含手机端分享的短链);创想云链接导入即将支持。
      </div>
    </van-dialog>
  </div>
</template>

<style scoped>
.clickable { cursor: pointer; }
.pb-listdot {
  width: 14px; height: 14px; border-radius: 50%; flex: none;
  border: 1.5px solid #fff; box-shadow: 0 0 0 1px #dcdee0;
}
.pb-select { width: 100%; border: 1px solid #ebedf0; border-radius: 6px; padding: 4px 8px; }
</style>
