<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  List,
  Refresh,
  Delete,
  VideoPlay,
  Close,
  Check,
  Warning,
  ArrowRight,
  Select,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()
const jobs = ref([])
const stats = ref(null)
const batchMode = ref(false)
const selected = ref(new Set())
const activeFilter = ref('all') // all, active, done, failed

async function load() {
  try {
    jobs.value = await api.get('/api/jobs?limit=100')
  } catch (e) {
    ElMessage.error(e.message || '获取任务失败')
  }
}

async function loadStats() {
  try {
    stats.value = await api.get('/api/jobs/stats')
  } catch {
    // 忽略
  }
}

const stateMap = {
  queued: { type: 'info', text: '排队中' },
  running: { type: 'primary', text: '运行中' },
  downloading: { type: 'primary', text: '下载模型' },
  slicing: { type: 'primary', text: '正在切片' },
  uploading: { type: 'primary', text: '推送固件' },
  printing: { type: 'success', text: '正在打印' },
  done: { type: 'success', text: '已完成' },
  failed: { type: 'danger', text: '执行失败' },
  cancelled: { type: 'info', text: '已取消' },
}

const filteredJobs = computed(() => {
  if (activeFilter.value === 'active') {
    return jobs.value.filter(j => ['queued', 'running', 'downloading', 'slicing', 'uploading', 'printing'].includes(j.state))
  }
  if (activeFilter.value === 'done') {
    return jobs.value.filter(j => j.state === 'done')
  }
  if (activeFilter.value === 'failed') {
    return jobs.value.filter(j => j.state === 'failed')
  }
  return jobs.value
})

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
    await ElMessageBox.confirm(
      `确定删除所选 ${selected.value.size} 个任务记录？产物与执行日志将一并清理。`,
      '批量删除确认',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    const r = await api.post('/api/jobs/batch-delete', { ids: [...selected.value] })
    ElMessage.success(`已删除 ${r.deleted} 个任务`)
    batchMode.value = false
    selected.value = new Set()
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

async function cancelJob(j) {
  try {
    await ElMessageBox.confirm(
      `确定取消任务 #${j.id}？打印机上正在进行的打印将同时中止。`,
      '取消打印确认',
      { confirmButtonText: '确定取消', cancelButtonText: '继续打印', type: 'warning' }
    )
    await api.post(`/api/jobs/${j.id}/cancel`)
    ElMessage.success('已发送取消指令')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '取消失败')
  }
}

async function retryJob(j) {
  try {
    await api.post(`/api/jobs/${j.id}/retry`)
    ElMessage.success(`任务 #${j.id} 已重新提交调度`)
    load()
  } catch (e) {
    ElMessage.error(e.message || '重试失败')
  }
}

async function delJob(j) {
  try {
    await ElMessageBox.confirm(`确定删除任务 #${j.id} 及其日志？`, '删除任务', {
      type: 'warning',
    })
    await api.del(`/api/jobs/${j.id}`)
    ElMessage.success('任务已删除')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

let timer = null
const onJob = () => load()

onMounted(() => {
  load()
  loadStats()
  store.on(onJob)
  timer = setInterval(load, 8000)
})
onUnmounted(() => {
  store.off(onJob)
  clearInterval(timer)
})
</script>

<template>
  <div class="pb-page">
    <div class="jobs-page-head">
      <div>
        <h1 class="page-title">打印与切片任务中心</h1>
        <p class="page-subtitle">查看一键打印全链路流水线、切片进度条、错误诊断与历史打印履历</p>
      </div>
      <div class="head-btn-group">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-if="jobs.length"
          :type="batchMode ? 'default' : 'primary'"
          plain
          @click="toggleBatch"
        >
          {{ batchMode ? '退出批量模式' : '批量管理' }}
        </el-button>
      </div>
    </div>

    <!-- 统计指标带 -->
    <div v-if="stats && stats.total" class="stats-banner">
      <div class="stat-cell">
        <span class="stat-k">累计任务数</span>
        <span class="stat-v">{{ stats.total }}</span>
      </div>
      <div class="stat-sep"></div>
      <div class="stat-cell">
        <span class="stat-k">综合成功率</span>
        <span class="stat-v text-success">{{ stats.success_rate ?? '-' }}%</span>
      </div>
      <div class="stat-sep"></div>
      <div class="stat-cell">
        <span class="stat-k">成功打印完成</span>
        <span class="stat-v font-bold">{{ stats.prints_completed }} 次</span>
      </div>
      <div v-if="stats.avg_slice_sec" class="stat-sep"></div>
      <div v-if="stats.avg_slice_sec" class="stat-cell">
        <span class="stat-k">平均切片耗时</span>
        <span class="stat-v">{{ stats.avg_slice_sec }} 秒</span>
      </div>
    </div>

    <!-- 状态筛选标签栏 -->
    <div class="filter-tabs-row">
      <div class="filter-tabs">
        <span class="ft-tab" :class="{ active: activeFilter === 'all' }" @click="activeFilter = 'all'">
          全部 ({{ jobs.length }})
        </span>
        <span class="ft-tab" :class="{ active: activeFilter === 'active' }" @click="activeFilter = 'active'">
          执行中
        </span>
        <span class="ft-tab" :class="{ active: activeFilter === 'done' }" @click="activeFilter = 'done'">
          已完成
        </span>
        <span class="ft-tab" :class="{ active: activeFilter === 'failed' }" @click="activeFilter = 'failed'">
          异常与失败
        </span>
      </div>
    </div>

    <!-- 空白状态 -->
    <div v-if="!jobs.length" class="empty-jobs-box">
      <div class="empty-icon">📦</div>
      <h3>暂无打印任务记录</h3>
      <p>前往「发现」模型库选择一个心仪的模型，体验一键直达打印机吧！</p>
      <el-button type="primary" @click="router.push('/search')">立即去探索模型</el-button>
    </div>

    <!-- 任务卡片列表 -->
    <div v-else class="jobs-list-grid">
      <div
        v-for="j in filteredJobs"
        :key="j.id"
        class="job-card"
        :class="{ 'is-selected': selected.has(j.id) }"
        @click="batchMode ? toggleSelect(j) : router.push(`/jobs/${j.id}`)"
      >
        <div class="job-card-header">
          <div class="header-left-meta">
            <el-checkbox
              v-if="batchMode"
              :model-value="selected.has(j.id)"
              :disabled="!selectable(j)"
              class="batch-chk"
              @click.stop
              @change="toggleSelect(j)"
            />
            <el-tag size="small" :type="stateMap[j.state]?.type || 'info'">
              {{ stateMap[j.state]?.text || j.state }}
            </el-tag>
            <span
              v-if="(j.payload?.filament_colors || [])[0]"
              class="filament-color-dot"
              :style="{ background: j.payload.filament_colors[0] }"
              :title="`耗材颜色: ${j.payload.filament_colors[0]}`"
            ></span>
            <span class="job-title-text">
              #{{ j.id }} {{ j.kind === 'slice' ? '单独切片' : '一键打印流水' }}
            </span>
          </div>

          <div class="header-actions" @click.stop>
            <template v-if="!batchMode">
              <el-button
                v-if="!['done', 'failed', 'cancelled'].includes(j.state)"
                size="small"
                type="warning"
                plain
                @click="cancelJob(j)"
              >
                取消
              </el-button>
              <template v-else>
                <el-button
                  v-if="j.state !== 'done'"
                  size="small"
                  type="primary"
                  plain
                  @click="retryJob(j)"
                >
                  重试
                </el-button>
                <el-button size="small" type="danger" plain @click="delJob(j)">
                  删除
                </el-button>
              </template>
            </template>
          </div>
        </div>

        <!-- 详细状态与进度 -->
        <div class="job-status-sub">
          <span class="sub-detail-text">{{ j.detail || j.error || '任务处理中...' }}</span>
          <span v-if="j.retries" class="retry-badge">已重试 {{ j.retries }} 次</span>
        </div>

        <div v-if="j.progress > 0 && j.state !== 'done'" class="job-progress-row">
          <el-progress
            :percentage="Math.round(j.progress * 100)"
            :status="j.state === 'failed' ? 'exception' : ''"
            :stroke-width="6"
          />
        </div>

        <div class="job-card-footer">
          <span class="time-text">{{ new Date(j.created_at).toLocaleString('zh-CN') }}</span>
          <span v-if="!batchMode" class="detail-link">
            查看详情与日志 <el-icon><ArrowRight /></el-icon>
          </span>
        </div>
      </div>
    </div>

    <!-- 底部批量浮动操作栏 -->
    <div v-if="batchMode && jobs.length" class="pb-batchbar">
      <el-checkbox :model-value="allSelected" @change="toggleAll">
        全选所有历史已结束任务
      </el-checkbox>
      <el-button
        type="danger"
        size="small"
        round
        :disabled="!selected.size"
        @click="batchDelete"
      >
        批量删除所选 ({{ selected.size }})
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.jobs-page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
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

.stats-banner {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: var(--pb-radius);
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}
.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.stat-k {
  font-size: 12px;
  color: #64748b;
}
.stat-v {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}
.stat-sep {
  width: 1px;
  height: 28px;
  background: #e2e8f0;
}

.filter-tabs-row {
  margin-bottom: 16px;
}
.filter-tabs {
  display: flex;
  gap: 8px;
}
.ft-tab {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s;
}
.ft-tab.active {
  background: #2563eb;
  color: #ffffff;
  font-weight: 600;
}

.empty-jobs-box {
  text-align: center;
  padding: 60px 20px;
  background: #ffffff;
  border-radius: var(--pb-radius);
  border: 1px dashed #cbd5e1;
}
.empty-icon { font-size: 40px; margin-bottom: 12px; }

.jobs-list-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.job-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
}
.job-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px -2px rgba(15, 23, 42, 0.08);
  border-color: #cbd5e1;
}
.job-card.is-selected {
  border-color: #2563eb;
  background: #eff6ff;
}

.job-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-chk { margin-right: 2px; }
.filament-color-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid rgba(0, 0, 0, 0.15);
  flex-shrink: 0;
}
.job-title-text {
  font-weight: 700;
  font-size: 14px;
  color: #0f172a;
}

.job-status-sub {
  font-size: 13px;
  color: #64748b;
  display: flex;
  justify-content: space-between;
}
.sub-detail-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.retry-badge {
  font-size: 11px;
  background: #fef2f2;
  color: #ef4444;
  padding: 1px 6px;
  border-radius: 4px;
}

.job-progress-row {
  margin: 2px 0;
}

.job-card-footer {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.time-text { color: #94a3b8; }
.detail-link {
  color: #2563eb;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 2px;
}

.text-success { color: #16a34a; }
.font-bold { font-weight: 700; }
</style>
