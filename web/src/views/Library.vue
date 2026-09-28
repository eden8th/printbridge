<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api, uploadFile } from '../api'
import { store } from '../store'

const models = ref([])
const batchMode = ref(false)
const selected = ref(new Set())

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
        <span class="pb-navbar-action" role="button"
              @click="models.length && toggleBatch()">
          {{ batchMode ? '退出管理' : '批量管理' }}
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
           @click="batchMode ? toggleSelect(m) : undefined">
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
          <van-icon v-if="!batchMode" name="delete-o" color="#ee0a24" size="20" @click="del(m)" />
        </div>
        <div v-for="f in m.files" :key="f.id"
             class="pb-row" style="margin-top:8px;background:#f7f8fa;border-radius:8px;padding:8px">
          <van-icon name="description" size="18" />
          <div class="pb-grow pb-ellipsis pb-muted">{{ f.name }} · {{ fmtSize(f.size) }}</div>
          <a v-if="!batchMode" :href="`/api/library/files/${f.id}/download`">
            <van-button size="mini" plain>下载</van-button>
          </a>
        </div>
      </div>
    </div>

    <!-- 批量操作栏 -->
    <div v-if="batchMode && models.length" class="pb-batchbar">
      <van-checkbox :model-value="allSelected" checked-color="#1989fa"
                    @update:model-value="toggleAll">全选</van-checkbox>
      <van-button type="danger" size="small" round :disabled="!selected.size"
                  @click="batchDelete">
        删除所选({{ selected.size }})
      </van-button>
    </div>
  </div>
</template>
