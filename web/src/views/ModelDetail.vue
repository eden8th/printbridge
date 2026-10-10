<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import PrintConfigPopup from '../components/PrintConfigPopup.vue'

const route = useRoute()
const router = useRouter()
const design = ref(null)
const loading = ref(true)
const selected = ref(null)          // 选中的 instance
const showPrint = ref(false)
const materialHint = ref('')        // 从模型版本名推断的材质期望
const nozzleHint = ref('')          // 从模型版本名推断的喷嘴
const hasToken = ref(true)   // 未拉到设置前默认有,避免误拦

// 从模型源下载需要用户本人凭证:没配则当场引导,避免任务提交后失败
async function ensureToken() {
  if (hasToken.value) return true
  try {
    await showConfirmDialog({
      title: '需要配置拓竹凭证',
      message: '下载 MakerWorld 模型需要你本人的账号 token(仅保存在本机,平台不托管账号)。现在去「设置」页配置?',
      confirmButtonText: '去配置',
      cancelButtonText: '取消',
    })
    router.push('/settings')
  } catch { /* 用户取消 */ }
  return false
}

// 从模型版本名自动推断喷嘴/材质(如 "0.2mm喷嘴, 0.06mm层高")
function inferNozzle(name) {
  const s = String(name || '')
  let m = s.match(/(\d+(?:\.\d+)?)\s*mm?\s*(?:喷嘴|喷头|nozzle)/i)
  if (!m) m = s.match(/(?:喷嘴|喷头|nozzle)\s*[:：]?\s*(\d+(?:\.\d+)?)/i)
  return m ? m[1] : ''
}
function inferMaterial(name) {
  const s = String(name || '').toUpperCase()
  for (const t of ['PETG', 'ABS', 'PLA', 'TPU', 'NYLON', 'ASA', 'PA-CF', 'PLA-CF'])
    if (s.includes(t)) return t
  return ''
}

// 换模型版本 → 自动填充喷嘴/材质期望(传入配置弹层)
watch(selected, () => {
  const name = selected.value?.name || ''
  materialHint.value = inferMaterial(name)
  nozzleHint.value = inferNozzle(name)
})

onMounted(async () => {
  try {
    design.value = await api.get(
      `/api/sources/${route.params.source}/design/${route.params.id}`)
    selected.value = design.value.instances[0] || null
    api.get('/api/settings').then((s) => {
      hasToken.value = !!s.makerworld?.token
    }).catch(() => {})
  } catch (e) {
    showFailToast(e.message)
  } finally {
    loading.value = false
  }
})

async function openPrint() {
  if (!(await ensureToken())) return
  showPrint.value = true
}

function onSubmitted(res) {
  showSuccessToast(`任务 #${res.job_id} 已提交`)
  router.push('/jobs')
}

async function importOnly() {
  if (!(await ensureToken())) return
  try {
    await api.post('/api/library/import', {
      source: route.params.source,
      design_id: route.params.id,
      instance_ids: selected.value ? [selected.value.instance_id] : [],
    })
    showSuccessToast('已加入下载队列')
    router.push('/library')
  } catch (e) {
    showFailToast(e.message)
  }
}
</script>

<template>
  <div class="pb-page" v-if="design">
    <van-nav-bar :title="design.title" left-arrow @click-left="router.back()" />
    <div class="pb-cols">
      <div class="pb-card">
        <img v-if="design.cover" :src="design.cover"
             style="width:100%;border-radius:8px;max-height:320px;object-fit:cover" />
        <h2 class="pb-title" style="margin-top:10px">{{ design.title }}</h2>
        <div class="pb-muted">@{{ design.author || '匿名' }} ·
          <a :href="design.source_url" target="_blank" rel="noopener">来源页</a></div>
        <div style="margin-top:10px" class="pb-muted summary"
             v-html="design.summary_html"></div>
      </div>

      <div>
      <van-radio-group v-model="selected">
        <van-cell v-for="inst in design.instances" :key="inst.instance_id" clickable>
          <template #title>
            <van-radio :name="inst" shape="dot">
              <span class="pb-ellipsis" style="display:inline-block;max-width:200px;vertical-align:bottom">
                {{ inst.name }}
              </span>
            </van-radio>
          </template>
        </van-cell>
      </van-radio-group>
      <van-empty v-if="!design.instances.length" description="该设计没有可下载文件" />
    </div>
    </div><!-- /pb-cols -->

    <van-button type="primary" block round size="large" :disabled="!selected"
                @click="openPrint">
      一键打印
    </van-button>
    <van-button block round style="margin-top:8px" :disabled="!selected" @click="importOnly">
      仅下载到模型库
    </van-button>

    <!-- 打印配置弹层(共用组件):basePayload 携带模型源定位,凭证已在 openPrint 校验 -->
    <PrintConfigPopup v-model:show="showPrint"
                      :base-payload="{
                        source: route.params.source,
                        design_id: route.params.id,
                        instance_id: selected?.instance_id,
                      }"
                      :material-hint="materialHint"
                      :nozzle-hint="nozzleHint"
                      @submitted="onSubmitted" />
  </div>

  <van-loading v-else-if="loading" center style="margin-top:40%">加载中...</van-loading>
  <van-empty v-else description="加载失败" />
</template>

<style scoped>
.summary :deep(img) { max-width: 100%; }
</style>
