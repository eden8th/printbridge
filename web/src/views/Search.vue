<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Search,
  Download,
  Star,
  Picture,
  ArrowRight,
  Link,
  Loading,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const router = useRouter()
const route = useRoute()
const keyword = ref('')
const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const sort = ref('score')
const page = ref(1)

const linkInput = ref('')
const parsingLink = ref(false)

const hotKeywords = ['龙', '收纳盒', '手机支架', '花瓶', '工具', '理线器', '钥匙扣']

const sorts = [
  { text: '综合相关度', value: 'score' },
  { text: '最多下载', value: 'downloadCount' },
  { text: '最多点赞', value: 'likeCount' },
  { text: '最新发布', value: 'newUploads' },
]

async function doSearch(reset = true) {
  if (!keyword.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    if (reset) page.value = 1
    const data = await api.get(
      `/api/sources/makerworld/search?keyword=${encodeURIComponent(keyword.value)}` +
      `&page=${page.value}&page_size=20&sort=${sort.value}`
    )
    items.value = reset ? data.items : [...items.value, ...data.items]
    total.value = data.total
    router.replace({ query: { ...route.query, kw: keyword.value, sort: sort.value } })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function selectHotKeyword(kw) {
  keyword.value = kw
  doSearch()
}

async function handleParseLink() {
  if (!linkInput.value.trim()) {
    return ElMessage.warning('请输入 MakerWorld 模型链接')
  }
  parsingLink.value = true
  try {
    const res = await api.post('/api/sources/parse-link', { url: linkInput.value.trim() })
    if (res.source && res.design_id) {
      router.push(`/model/${res.source}/${res.design_id}`)
    } else {
      ElMessage.error('无法解析该链接，请确认是否为合法的 MakerWorld 模型地址')
    }
  } catch (err) {
    ElMessage.error(err.message || '链接解析失败')
  } finally {
    parsingLink.value = false
  }
}

onMounted(() => {
  if (route.query.kw) {
    keyword.value = String(route.query.kw)
    if (route.query.sort) sort.value = String(route.query.sort)
    doSearch()
  }
})

function loadMore() {
  page.value += 1
  doSearch(false)
}

function fmt(n) {
  return n >= 10000 ? `${(n / 10000).toFixed(1)}w` : String(n || 0)
}
</script>

<template>
  <div class="pb-page">
    <!-- 英雄搜索横幅 -->
    <div class="search-hero-card">
      <div class="hero-header">
        <h1 class="hero-title">探索 3D 模型宇宙</h1>
        <p class="hero-desc">直连 MakerWorld 官方模型库，海量 3MF/STL 设计一键下载、自动切片、直推打印机</p>
      </div>

      <!-- 搜索主输入框 -->
      <div class="search-input-wrap">
        <el-input
          v-model="keyword"
          size="large"
          placeholder="搜索模型：龙、花瓶、手机支架、机械收纳盒…"
          :prefix-icon="Search"
          clearable
          class="hero-search-input"
          @keyup.enter="doSearch()"
        >
          <template #append>
            <el-button type="primary" :loading="loading" @click="doSearch()">
              立即搜索
            </el-button>
          </template>
        </el-input>
      </div>

      <!-- 快捷热门标签与排序 -->
      <div class="hero-tags-row">
        <div class="hot-tags">
          <span class="tag-title">热门探索:</span>
          <span
            v-for="kw in hotKeywords"
            :key="kw"
            class="hot-chip"
            :class="{ active: keyword === kw }"
            @click="selectHotKeyword(kw)"
          >
            {{ kw }}
          </span>
        </div>

        <div class="sort-selector">
          <span
            v-for="s in sorts"
            :key="s.value"
            class="sort-chip"
            :class="{ active: sort === s.value }"
            @click="sort = s.value; doSearch()"
          >
            {{ s.text }}
          </span>
        </div>
      </div>

      <!-- 链接一键解析导入栏 -->
      <div class="link-import-bar">
        <div class="link-icon-box">
          <el-icon><Link /></el-icon>
          <span>粘贴直通:</span>
        </div>
        <el-input
          v-model="linkInput"
          placeholder="支持粘贴 makerworld.com/zh/models/xxxx 链接直达模型"
          size="small"
          clearable
          style="flex: 1;"
          @keyup.enter="handleParseLink"
        />
        <el-button size="small" type="primary" plain :loading="parsingLink" @click="handleParseLink">
          解析并直达
        </el-button>
      </div>
    </div>

    <!-- 结果统计与错误展示 -->
    <div v-if="error" class="error-notice">
      {{ error }}
    </div>

    <div v-if="total" class="result-bar">
      <span>检索到 <strong>{{ total }}</strong> 个可打印模型设计</span>
      <span class="source-tag">数据源: MakerWorld 官方节点</span>
    </div>

    <!-- 空白状态 -->
    <div v-if="!items.length && !loading" class="empty-state">
      <div class="empty-icon">🔍</div>
      <div class="empty-title">输入关键词或选择热门标签开始探索</div>
      <div class="empty-sub">支持直接搜索任意中文关键词，或在上方粘贴 MakerWorld 分享链接</div>
    </div>

    <!-- 响应式模型卡片网格 -->
    <div class="models-grid">
      <div
        v-for="it in items"
        :key="it.id"
        class="model-card"
        @click="router.push(`/model/makerworld/${it.id}`)"
      >
        <div class="card-cover-wrap">
          <img :src="it.cover" :alt="it.title" class="model-cover" loading="lazy" />
          <div class="cover-overlay">
            <span class="quick-view-badge">查看设计详情 <el-icon><ArrowRight /></el-icon></span>
          </div>
        </div>
        <div class="card-info">
          <h3 class="model-title" :title="it.title">{{ it.title }}</h3>
          <div class="model-author">
            <span>@{{ it.author || '匿名创作者' }}</span>
          </div>
          <div class="model-stats">
            <span class="stat-pill">
              <el-icon><Star /></el-icon> {{ fmt(it.likes) }}
            </span>
            <span class="stat-pill">
              <el-icon><Download /></el-icon> {{ fmt(it.downloads) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 加载与分页 -->
    <div v-if="loading" class="loading-wrap">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <span>正在为您检索最新模型数据...</span>
    </div>

    <div v-if="items.length && items.length < total" class="loadmore-wrap">
      <el-button round size="default" :loading="loading" @click="loadMore">
        加载更多设计 (已载入 {{ items.length }} / {{ total }})
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.search-hero-card {
  background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
  border-radius: var(--pb-radius);
  padding: 24px 28px;
  border: 1px solid #dbeafe;
  box-shadow: 0 4px 20px -2px rgba(37, 99, 235, 0.08);
  margin-bottom: 24px;
}

.hero-header {
  margin-bottom: 18px;
}
.hero-title {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.5px;
}
.hero-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
}

.search-input-wrap {
  margin-bottom: 14px;
}
:deep(.hero-search-input .el-input__wrapper) {
  border-radius: 10px 0 0 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
:deep(.hero-search-input .el-input-group__append) {
  border-radius: 0 10px 10px 0;
  background-color: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
}

.hero-tags-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.hot-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tag-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}
.hot-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}
.hot-chip:hover, .hot-chip.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
  font-weight: 600;
}

.sort-selector {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.sort-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 14px;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sort-chip.active {
  background: #2563eb;
  color: #ffffff;
  font-weight: 600;
}

.link-import-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px dashed #cbd5e1;
  padding: 8px 14px;
  border-radius: 10px;
}
.link-icon-box {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.result-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-size: 13px;
  color: #475569;
}
.source-tag {
  background: #eff6ff;
  color: #2563eb;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  background: #ffffff;
  border-radius: var(--pb-radius);
  border: 1px dashed #cbd5e1;
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}
.empty-title {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}
.empty-sub {
  font-size: 13px;
  color: #64748b;
  margin-top: 6px;
}

.models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 20px;
}

.model-card {
  background: #ffffff;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s ease;
}
.model-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px -4px rgba(15, 23, 42, 0.1);
  border-color: #cbd5e1;
}

.card-cover-wrap {
  position: relative;
  width: 100%;
  padding-top: 75%;
  background: #f1f5f9;
  overflow: hidden;
}
.model-cover {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}
.model-card:hover .model-cover {
  transform: scale(1.04);
}
.cover-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(15, 23, 42, 0.6) 0%, transparent 60%);
  opacity: 0;
  display: flex;
  align-items: flex-end;
  padding: 12px;
  transition: opacity 0.2s ease;
}
.model-card:hover .cover-overlay {
  opacity: 1;
}
.quick-view-badge {
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}

.card-info {
  padding: 14px;
  display: flex;
  flex-direction: column;
  flex: 1;
}
.model-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-author {
  font-size: 12px;
  color: #64748b;
  margin: 4px 0 10px;
}
.model-stats {
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stat-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 500;
}

.loading-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: #64748b;
  font-size: 14px;
}
.loadmore-wrap {
  text-align: center;
  margin: 30px 0;
}
.error-notice {
  background: #fef2f2;
  color: #ef4444;
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  border: 1px solid #fecaca;
}
</style>
