<script setup>
import { computed, onMounted, ref, watch } from 'vue'
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
const nozzle = ref('')
const processId = ref('')
const filamentId = ref('')
const color = ref('#E3E3E3')
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

const bundle = computed(() => profiles.value.find((b) => b.key === bundleKey.value))
const nozzles = computed(() => bundle.value?.nozzles || [])
const filaments = computed(() =>
  bundle.value?.filaments?.find((f) => f.nozzle === nozzle.value)?.items || [])
const processes = computed(() =>
  bundle.value?.processes?.find((f) => f.nozzle === nozzle.value)?.items || [])
const machineId = computed(() =>
  nozzles.value.find((n) => n.nozzle === nozzle.value)?.machine_id || '')
const cfsConnected = computed(() => {
  const t = store.printers[printerId.value]
  return !!(t && t.cfs_connected)
})

// 切换喷嘴后,耗材/工艺若在新喷嘴下不存在则重置为默认
watch(nozzle, () => {
  if (!filaments.value.some((f) => f.id === filamentId.value)) {
    filamentId.value = filaments.value.find((f) => f.name === 'CR-PLA')?.id
      || filaments.value[0]?.id || ''
  }
  if (!processes.value.some((p) => p.id === processId.value)) {
    processId.value = processes.value.find((p) => p.name.includes('0.20mm Standard'))?.id
      || processes.value[0]?.id || ''
  }
})

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
      nozzle.value = pr[0].nozzles?.some((n) => n.nozzle === '0.4') ? '0.4'
        : (pr[0].nozzles?.[0]?.nozzle || '')
      // nozzle 的 watch 会自动补齐耗材/工艺默认值
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
  if (!machineId.value) return showFailToast('请选择喷嘴直径')
  if (!filamentId.value) return showFailToast('请选择耗材材质')
  try {
    const res = await api.post('/api/jobs/oneclick', {
      source: route.params.source,
      design_id: route.params.id,
      instance_id: selected.value?.instance_id,
      printer_id: printerId.value,
      bundle: bundleKey.value,
      machine_id: machineId.value,
      filament_ids: [filamentId.value],
      filament_colors: [color.value],
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
      <van-cell title="机型" :value="bundle?.name || bundleKey" />
      <van-field label="喷嘴直径" readonly>
        <template #input>
          <van-radio-group v-model="nozzle" direction="horizontal">
            <van-radio v-for="n in nozzles" :key="n.nozzle" :name="n.nozzle">
              {{ n.nozzle }} mm
            </van-radio>
          </van-radio-group>
        </template>
      </van-field>
      <van-field label="耗材材质" readonly>
        <template #input>
          <select v-model="filamentId" class="pb-select">
            <option v-for="f in filaments" :key="f.id" :value="f.id">
              {{ f.name }}{{ f.type ? `(${f.type})` : '' }}
            </option>
          </select>
        </template>
      </van-field>
      <van-field label="打印颜色" readonly>
        <template #input>
          <div class="pb-colors">
            <span v-for="c in PRESET_COLORS" :key="c" class="pb-dot"
                  :class="{ active: color.toLowerCase() === c }"
                  :style="{ background: c }" @click="color = c"></span>
            <label class="pb-dot pb-dot-custom" :style="{ background: color }"
                   title="自定义颜色">
              <input type="color" v-model="color" style="display:none" />
              <van-icon name="plus" color="#fff" />
            </label>
          </div>
        </template>
      </van-field>
      <van-field label="工艺层厚" readonly>
        <template #input>
          <select v-model="processId" class="pb-select">
            <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </template>
      </van-field>
      <div v-if="cfsConnected" class="pb-muted" style="padding:2px 4px 6px">
        🎨 CFS 已连接:开始打印前请确认所选颜色的料道已装载耗材
      </div>
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
.pb-colors { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.pb-dot {
  width: 26px; height: 26px; border-radius: 50%; cursor: pointer;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0; display: inline-flex;
  align-items: center; justify-content: center;
}
.pb-dot.active { box-shadow: 0 0 0 2px var(--pb-primary); }
.pb-dot-custom { box-shadow: inset 0 0 0 1px rgba(255,255,255,.6), 0 0 0 1px #dcdee0; }
</style>
