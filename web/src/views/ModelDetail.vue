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
const nozzle = ref('')
const processId = ref('')
const filamentId = ref('')
const color = ref('#F2F2F2')
const autoStart = ref(true)
const hasToken = ref(true)   // 未拉到设置前默认有,避免误拦
const cfsInfo = ref(null)    // 打印机 CFS 料道状态

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

// 机型参数包跟随所选打印机的机型(打印机设置里选择)
const printer = computed(() => printers.value.find((p) => p.id === printerId.value))
const bundle = computed(() => {
  const key = printer.value?.settings?.model
  return profiles.value.find((b) => b.key === key) || profiles.value[0] || null
})
const modelMissing = computed(() => !!printer.value && !printer.value.settings?.model)
const nozzles = computed(() => bundle.value?.nozzles || [])
const machineId = computed(() =>
  nozzles.value.find((n) => n.nozzle === nozzle.value)?.machine_id || '')

// 耗材/工艺按需拉取(机型+喷嘴)
const optionsCache = ref({})
const optionsKey = computed(() =>
  bundle.value && nozzle.value ? `${bundle.value.key}|${nozzle.value}` : '')
const filaments = computed(() => optionsCache.value[optionsKey.value]?.filaments || [])
const processes = computed(() => optionsCache.value[optionsKey.value]?.processes || [])
const materialHint = ref('')   // 从模型版本名推断的材质期望

// 常见耗材预设色(无 CFS 料道数据时手动匹配)
const PRESET_COLORS = [
  { c: '#1A1A1A', n: '黑' }, { c: '#F2F2F2', n: '白' }, { c: '#8C8C8C', n: '灰' },
  { c: '#D32F2F', n: '红' }, { c: '#F57C00', n: '橙' }, { c: '#FBC02D', n: '黄' },
  { c: '#388E3C', n: '绿' }, { c: '#1976D2', n: '蓝' }, { c: '#7B1FA2', n: '紫' },
  { c: '#795548', n: '棕' },
]
const selectedColorName = computed(() => {
  const c = (color.value || '').toLowerCase()
  const p = PRESET_COLORS.find((x) => x.c.toLowerCase() === c)
  if (p) return p.n
  const s = cfsSlots.value.find((x) => x.color.toLowerCase() === c)
  return s ? `CFS ${s.box}-${s.index}` : '自定义'
})

// CFS 料道(真实颜色/材质,SSH 只读读取)
const cfsSlots = computed(() => {
  const out = []
  for (const b of cfsInfo.value?.boxes || []) {
    (b.slots || []).forEach((s, i) => {
      if (s.color) out.push({ ...s, index: s.index || i + 1, box: b.box })
    })
  }
  return out
})

function pickCfsSlot(s) {
  color.value = s.color
  const f = filaments.value.find((x) =>
    (x.type || '').toUpperCase().includes((s.material || '').toUpperCase()))
  if (f) filamentId.value = f.id
}

const colorHint = computed(() => {
  if (cfsSlots.value.length)
    return '✅ 已读取 CFS 料道(真实颜色):点击料道自动匹配耗材;开始打印前请确认打印机当前供料料道一致'
  if (!cfsInfo.value || cfsInfo.value.available === false)
    return '常见耗材预设色;切片配色写入 G-code,实际供料由打印机当前装料决定'
  if (cfsInfo.value.connected)
    return 'CFS 已连接,但未读到料道明细(需在打印机编辑里配置 SSH 密码)'
  return '检测到 CFS 能力但未读到料道装料;打印将使用打印机当前装料料道'
})

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

function pickDefaults() {
  if (!bundle.value) return
  nozzle.value = bundle.value.nozzles?.some((n) => n.nozzle === '0.4') ? '0.4'
    : (bundle.value.nozzles?.[0]?.nozzle || '')
}

async function loadOptions() {
  if (!bundle.value || !nozzle.value) return
  const k = optionsKey.value
  if (optionsCache.value[k]) return ensureDefaults()
  try {
    const o = await api.get(
      `/api/profiles/${bundle.value.key}/options?nozzle=${encodeURIComponent(nozzle.value)}`)
    optionsCache.value = { ...optionsCache.value, [k]: o }
  } catch { /* 拉取失败时下拉为空,提交前有校验 */ }
  ensureDefaults()
}

function ensureDefaults() {
  const fil = filaments.value
  if (!fil.length) return
  if (materialHint.value) {
    const f = fil.find((x) => (x.type || '').toUpperCase().includes(materialHint.value))
    if (f) {
      filamentId.value = f.id
      materialHint.value = ''
      return
    }
  }
  if (!fil.some((x) => x.id === filamentId.value)) {
    filamentId.value = fil.find((x) => x.name === 'CR-PLA')?.id || fil[0]?.id || ''
  }
  const pro = processes.value
  if (!pro.some((x) => x.id === processId.value)) {
    processId.value = pro.find((x) => x.name.includes('0.20mm Standard'))?.id
      || pro[0]?.id || ''
  }
}

// 换打印机 → 机型/参数包/CFS 状态联动
watch(printerId, async () => {
  pickDefaults()
  cfsInfo.value = null
  if (printerId.value) {
    try { cfsInfo.value = await api.get(`/api/printers/${printerId.value}/cfs`) }
    catch { cfsInfo.value = null }
  }
})

// 换模型版本 → 自动填充喷嘴/材质
watch(selected, () => {
  const name = selected.value?.name || ''
  materialHint.value = inferMaterial(name)
  const nz = inferNozzle(name)
  if (nz && nozzles.value.some((n) => n.nozzle === nz)) nozzle.value = nz
})

// 机型/喷嘴变化 → 拉取对应耗材工艺
watch([bundle, nozzle], () => loadOptions())

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
    if (ps.length) printerId.value = ps[0].id
  } catch (e) {
    showFailToast(e.message)
  } finally {
    loading.value = false
  }
})

async function submitOneClick() {
  if (!(await ensureToken())) return
  if (!bundle.value) return showFailToast('打印机未设置机型:请到「打印机→编辑」选择')
  if (!machineId.value) return showFailToast('请选择喷嘴直径')
  if (!filamentId.value) return showFailToast('请选择耗材材质')
  try {
    const res = await api.post('/api/jobs/oneclick', {
      source: route.params.source,
      design_id: route.params.id,
      instance_id: selected.value?.instance_id,
      printer_id: printerId.value,
      bundle: bundle.value.key,
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
                :value="printer?.name || '请先添加打印机'"
                @click="!printers.length && router.push('/printers')" />
      <van-cell title="机型" :value="bundle?.name || '未设置'" />
      <div v-if="modelMissing" class="pb-muted" style="padding:0 16px 4px">
        该打印机未设置机型,当前使用默认参数包;可在「打印机 → 编辑」中选择正确机型
      </div>
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
            <template v-if="cfsSlots.length">
              <span v-for="s in cfsSlots" :key="s.box + s.slot"
                    class="pb-dot" :class="{ active: color.toLowerCase() === s.color.toLowerCase() }"
                    :style="{ background: s.color }"
                    :title="`CFS 料道${s.index} · ${s.material} · ${s.name}`"
                    @click="pickCfsSlot(s)">
                <span class="pb-slotnum">{{ s.index }}</span>
              </span>
              <span class="pb-slotsep">|</span>
            </template>
            <span v-for="c in PRESET_COLORS" :key="c.c" class="pb-dot"
                  :class="{ active: color.toLowerCase() === c.c }"
                  :style="{ background: c.c }" :title="c.n" @click="color = c.c"></span>
          </div>
        </template>
      </van-field>
      <div class="pb-muted" style="padding:0 16px 4px">
        {{ selectedColorName }} · {{ colorHint }}
      </div>
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
.pb-colors { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.pb-dot {
  width: 26px; height: 26px; border-radius: 50%; cursor: pointer;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0; display: inline-flex;
  align-items: center; justify-content: center;
}
.pb-dot.active { box-shadow: 0 0 0 2px var(--pb-primary); }
.pb-slotnum {
  font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; font-weight: 700;
}
.pb-slotsep { color: #dcdee0; margin: 0 2px; }
</style>
