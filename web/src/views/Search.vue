<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

const sorts = [
  { text: '相关度', value: 'score' },
  { text: '最多下载', value: 'downloadCount' },
  { text: '最多点赞', value: 'likeCount' },
  { text: '最新', value: 'newUploads' },
]

async function doSearch(reset = true) {
  if (!keyword.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    if (reset) page.value = 1
    const data = await api.get(
      `/api/sources/makerworld/search?keyword=${encodeURIComponent(keyword.value)}` +
      `&page=${page.value}&page_size=20&sort=${sort.value}`)
    items.value = reset ? data.items : [...items.value, ...data.items]
    total.value = data.total
    // 同步到地址栏,便于分享/刷新保持
    router.replace({ query: { ...route.query, kw: keyword.value, sort: sort.value } })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // 深链:/search?kw=龙&sort=downloadCount
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
  return n >= 10000 ? `${(n / 10000).toFixed(1)}w` : String(n)
}
</script>

<template>
  <div class="pb-page">
    <div class="pb-card pb-searchcard">
      <van-search v-model="keyword" placeholder="搜索模型:龙、花瓶、手机支架…"
                  @search="doSearch()" />
      <div class="pb-filters">
        <span v-for="s in sorts" :key="s.value" class="pb-chip"
              :class="{ active: sort === s.value }"
              @click="sort = s.value; doSearch()">
          {{ s.text }}
        </span>
      </div>
    </div>

    <van-empty v-if="!items.length && !loading" description="输入关键词开始探索" />

    <van-cell v-if="total" :title="`共 ${total} 个结果`" class="pb-muted" />

    <div class="pb-grid">
      <div v-for="it in items" :key="it.id" class="pb-card pb-row clickable"
           @click="router.push(`/model/makerworld/${it.id}`)">
        <img class="pb-thumb" :src="it.cover" loading="lazy" />
        <div class="pb-grow">
          <div style="font-weight:600" class="pb-ellipsis">{{ it.title }}</div>
          <div class="pb-muted pb-ellipsis" style="margin-top:4px">@{{ it.author || '匿名' }}</div>
          <div class="pb-muted" style="margin-top:6px">
            <van-icon name="good-job-o" /> {{ fmt(it.likes) }}
            &nbsp;<van-icon name="down" /> {{ fmt(it.downloads) }}
          </div>
        </div>
        <van-icon name="arrow" color="#c8c9cc" />
      </div>
    </div>

    <van-loading v-if="loading" center style="margin:20px">加载中...</van-loading>
    <div v-if="items.length && items.length < total" style="text-align:center;margin:8px">
      <van-button plain size="small" round @click="loadMore">加载更多</van-button>
    </div>
    <van-notice-bar v-if="error" wrapable :scrollable="false" color="#ee0a24" background="#fff1f1">
      {{ error }}
    </van-notice-bar>
  </div>
</template>

<style scoped>
.clickable { cursor: pointer; }
.pb-searchcard { padding: 6px 8px 10px; }
.pb-searchcard :deep(.van-search) { padding: 4px 0 0; background: transparent; }
.pb-searchcard :deep(.van-search__content) {
  border-radius: 10px; background: #f2f3f5;
}
.pb-filters {
  display: flex; gap: 8px; padding: 8px 10px 0; flex-wrap: wrap;
}
.pb-chip {
  font-size: 12px; padding: 4px 12px; border-radius: 14px; cursor: pointer;
  background: #f2f3f5; color: #4b5563; user-select: none;
  transition: background .15s, color .15s;
}
.pb-chip.active { background: #e8f1ff; color: var(--pb-primary); font-weight: 600; }
</style>
