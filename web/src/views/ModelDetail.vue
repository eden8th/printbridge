<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { api } from '../api'
import { store } from '../store'

const route = useRoute()
const router = useRouter()
const design = ref(null)
const loading = ref(true)
const selected = ref(null)          // 选中的 instance
const showPrint = ref(false)

// 一键打印表单
const printers = ref([])
const profiles = ref([])
const printerId = ref(null)
const bundleKey = ref('')
const machineId = ref('')
const processId = ref('')
const filamentId = ref('')
const autoStart = ref(true)
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

const bundles = computed(() => profiles.value)
const machines = computed(() =>
  (profiles.value.find((b) => b.key === bundleKey.value)?.machines) || [])
const processes = computed(() =>
  (profiles.value.find((b) => b.key === bundleKey.value)?.processes) || [])
const filaments = computed(() =>
  (profiles.value.find((b) => b.key === bundleKey.value)?.filaments) || [])

onMounted(async () => {
  try {
    design.value = await api.get(
      `/api/sources/${route.params.source}/design/${route.params.id}`)
    selected.value = design.value.instances[0] || null
    const [ps, pr] = await Promise.all([api.get('/api/printers'), api.get('/api/profiles')])
    printers.value = ps
    profiles.value = pr
    api.get('/api/settings').then((s) => {
      hasToken.value = !!s.makerworld?.token
    }).catch(() => {})
    if (pr.length) {
      bundleKey.value = pr[0].key
      machineId.value = pr[0].machines.find((m) => m.id.includes('0.4'))?.id
        || pr[0].machines[0]?.id || ''
      processId.value = pr[0].processes.find((m) => m.name.includes('0.20mm Standard'))?.id
        || pr[0].processes[0]?.id || ''
      filamentId.value = pr[0].filaments.find((m) => m.name === 'CR-PLA')?.id
        || pr[0].filaments[0]?.id || ''
    }
    if (ps.length) printerId.value = ps[0].id
  } catch (e) {
    showFailToast(e.message)
  } finally {
    loading.value = false
  }
})

async function submitOneClick() {
  if (!(await ensureToken())) return
  try {
    const res = await api.post('/api/jobs/oneclick', {
      source: route.params.source,
      design_id: route.params.id,
      instance_id: selected.value?.instance_id,
      printer_id: printerId.value,
      bundle: bundleKey.value,
      machine_id: machineId.value,
      filament_ids: filamentId.value ? [filamentId.value] : [],
      process_id: processId.value,
      auto_start: autoStart.value,
    })
    showPrint.value = false
    showSuccessToast(`任务 #${res.job_id} 已提交`)
    router.push('/jobs')
  } catch (e) {
    showFailToast(e.message)
  }
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
    <div class="pb-card">
      <img v-if="design.cover" :src="design.cover"
           style="width:100%;border-radius:8px;max-height:320px;object-fit:cover" />
      <h2 class="pb-title" style="margin-top:10px">{{ design.title }}</h2>
      <div class="pb-muted">@{{ design.author || '匿名' }} ·
        <a :href="design.source_url" target="_blank" rel="noopener">来源页</a></div>
      <div style="margin-top:10px" class="pb-muted summary"
           v-html="design.summary_html"></div>
    </div>

    <div class="pb-card">
      <h3 class="pb-title">选择要打印的版本</h3>
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

    <van-button type="primary" block round size="large" :disabled="!selected"
                @click="showPrint = true">
      一键打印
    </van-button>
    <van-button block round style="margin-top:8px" :disabled="!selected" @click="importOnly">
      仅下载到模型库
    </van-button>

    <!-- 一键打印配置弹层 -->
    <van-popup v-model:show="showPrint" position="bottom" round style="padding:16px">
      <h3 class="pb-title">一键打印配置</h3>
      <van-cell title="打印机" is-link
                :value="printers.find((p) => p.id === printerId)?.name || '请先添加打印机'"
                @click="!printers.length && router.push('/printers')" />
      <van-cell title="机型参数包" is-link :value="bundleKey" disabled />
      <van-field label="机器配置" readonly>
        <template #input>
          <select v-model="machineId" class="pb-select">
            <option v-for="m in machines" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </template>
      </van-field>
      <van-field label="耗材" readonly>
        <template #input>
          <select v-model="filamentId" class="pb-select">
            <option v-for="f in filaments" :key="f.id" :value="f.id">{{ f.name }}</option>
          </select>
        </template>
      </van-field>
      <van-field label="工艺层厚" readonly>
        <template #input>
          <select v-model="processId" class="pb-select">
            <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </template>
      </van-field>
      <van-cell title="切片后自动开始打印">
        <template #right-icon>
          <van-switch v-model="autoStart" size="22" />
        </template>
      </van-cell>
      <van-button type="primary" block round style="margin-top:10px"
                  :disabled="!printerId" @click="submitOneClick">
        开始下载并切片
      </van-button>
      <div v-if="!printers.length" class="pb-muted" style="text-align:center;margin-top:8px">
        还没有打印机,请到「打印机」页添加
      </div>
    </van-popup>
  </div>

  <van-loading v-else-if="loading" center style="margin-top:40%">加载中...</van-loading>
  <van-empty v-else description="加载失败" />
</template>

<style scoped>
.summary :deep(img) { max-width: 100%; }
.pb-select { width: 100%; border: 1px solid #ebedf0; border-radius: 6px; padding: 4px 8px; }
</style>
