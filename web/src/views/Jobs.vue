<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()
const jobs = ref([])
const stats = ref(null)
const batchMode = ref(false)
const selected = ref(new Set())

async function load() {
  try {
    jobs.value = await api.get('/api/jobs?limit=100')
  } catch (e) {
    showFailToast(e.message)
  }
}

async function loadStats() {
  try { stats.value = await api.get('/api/jobs/stats') } catch { /* 静默 */ }
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

const selectable = (j) => ['done', 'failed', 'cancelled'].includes(j.state)

function toggleBatch() {
  batchMode.value = !batchMode.value
  selected.value = new Set()
}

function toggleSelect(j) {
  if (!selectable(j)) return
  const s = new Set(selected.value)
  if (s.has(j.id)) s.delete(j.id)
  else s.add(j.id)
  selected.value = s
}

const selectableIds = computed(() => jobs.value.filter(selectable).map((j) => j.id))
const allSelected = computed(() =>
  selectableIds.value.length > 0 && selectableIds.value.every((id) => selected.value.has(id)))

function toggleAll() {
  selected.value = new Set(allSelected.value ? [] : selectableIds.value)
}

async function batchDelete() {
  if (!selected.value.size) return
  try {
    await showConfirmDialog({
      title: '批量删除',
      message: `确定删除所选 ${selected.value.size} 个任务?记录与日志将一并删除。`,
    })
  } catch { return }
  try {
    const r = await api.post('/api/jobs/batch-delete', { ids: [...selected.value] })
    showSuccessToast(`已删除 ${r.deleted} 个${r.skipped ? `(跳过进行中 ${r.skipped} 个)` : ''}`)
    batchMode.value = false
    selected.value = new Set()
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

async function cancelJob(j) {
  try {
    await api.post(`/api/jobs/${j.id}/cancel`)
    load()
  } catch (e) {
    showFailToast(e.message)
  }
}

async function retryJob(j) {
  try {
    await api.post(`/api/jobs/${j.id}/retry`)
    showSuccessToast(`任务 #${j.id} 已重新入队`)
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
  loadStats()
  store.on(onJob)
  timer = setInterval(load, 8000)
})
onUnmounted(() => { store.off(onJob); clearInterval(timer) })
</script>

<template>
  <div class="pb-page">
    <van-nav-bar title="打印任务">
      <template #right>
        <span class="pb-navbar-action" role="button"
              @click="jobs.length && toggleBatch()">
          {{ batchMode ? '退出管理' : '批量管理' }}
        </span>
      </template>
    </van-nav-bar>

    <!-- 使用统计(北极星:成功打印次数) -->
    <div v-if="stats && stats.total" class="pb-muted pb-row"
         style="padding:6px 16px;font-size:12px;justify-content:center">
      <span>任务 {{ stats.total }}</span><span>·</span>
      <span>成功率 {{ stats.success_rate ?? '-' }}%</span><span>·</span>
      <span>成功打印 {{ stats.prints_completed }} 次</span><span v-if="stats.avg_slice_sec">·</span>
      <span v-if="stats.avg_slice_sec">平均切片 {{ stats.avg_slice_sec }}s</span>
    </div>

    <van-empty v-if="!jobs.length" description="还没有任务。去「发现」页挑个模型一键打印吧" />

    <div class="pb-grid">
      <div v-for="j in jobs" :key="j.id" class="pb-card clickable"
           @click="batchMode ? toggleSelect(j) : router.push(`/jobs/${j.id}`)">
        <div class="pb-row">
          <van-checkbox v-if="batchMode" :model-value="selected.has(j.id)"
                        :disabled="!selectable(j)" checked-color="#1989fa"
                        style="margin-right:4px"
                        @click.stop @update:model-value="toggleSelect(j)" />
          <van-tag :color="stateColor[j.state] || '#969799'">{{ j.state }}</van-tag>
          <span v-if="(j.payload?.filament_colors || [])[0]" class="pb-listdot"
                :style="{ background: j.payload.filament_colors[0] }"></span>
          <div class="pb-grow pb-ellipsis" style="font-weight:600">
            #{{ j.id }} {{ j.kind === 'slice' ? '切片任务' : '一键打印' }}
          </div>
          <template v-if="!batchMode">
            <van-button v-if="!['done', 'failed', 'cancelled'].includes(j.state)"
                        size="mini" plain type="warning" @click.stop="cancelJob(j)">
              取消
            </van-button>
            <template v-else>
              <van-button v-if="j.state !== 'done'" size="mini" plain type="primary"
                          @click.stop="retryJob(j)">重试</van-button>
              <van-button size="mini" plain type="danger" @click.stop="delJob(j)">
                删除
              </van-button>
            </template>
          </template>
        </div>
        <div class="pb-muted" style="margin-top:6px">
          {{ j.detail || j.error || '等待中' }}
          <span v-if="progressText(j)"> · {{ progressText(j) }}</span>
          <span v-if="j.retries"> · 已重试 {{ j.retries }} 次</span>
        </div>
        <van-progress v-if="j.progress > 0 && j.state !== 'done'"
                      :percentage="Math.round(j.progress * 100)" style="margin-top:8px" />
        <div class="pb-muted pb-row" style="margin-top:6px">
          <span class="pb-grow">{{ new Date(j.created_at).toLocaleString('zh-CN') }}</span>
          <span v-if="!batchMode">详情 <van-icon name="arrow" /></span>
        </div>
      </div>
    </div>

    <!-- 批量操作栏 -->
    <div v-if="batchMode && jobs.length" class="pb-batchbar">
      <van-checkbox :model-value="allSelected" checked-color="#1989fa"
                    @update:model-value="toggleAll">全选(可删任务)</van-checkbox>
      <van-button type="danger" size="small" round :disabled="!selected.size"
                  @click="batchDelete">
        删除所选({{ selected.size }})
      </van-button>
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
