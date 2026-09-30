<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { showFailToast } from 'vant'
import { api } from '../api'

/**
 * 共用「打印配置弹层」:打印机/机型/喷嘴/耗材/颜色(CFS 料道)/工艺/自动开打。
 * basePayload 里携带任务定位参数:
 *   - 模型库文件:{ model_file_id }
 *   - 模型源一键打印:{ source, design_id, instance_id }(由父页在提交前处理凭证)
 */
const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: '一键打印配置' },
  basePayload: { type: Object, default: () => ({}) },
  materialHint: { type: String, default: '' },   // 从模型版本名推断的材质期望
  nozzleHint: { type: String, default: '' },     // 从模型版本名推断的喷嘴
})
const emit = defineEmits(['update:show', 'submitted'])

const printers = ref([])
const profiles = ref([])
const printerId = ref(null)
const nozzle = ref('')
const processId = ref('')
const filamentId = ref('')
const color = ref('#F2F2F2')
const cfsTnn = ref('')      // 选中的 CFS 料道(如 T1A),打印前自动换料
const autoStart = ref(true)
const cfsInfo = ref(null)   // 打印机 CFS 料道状态
const submitting = ref(false)

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

// 常见耗材预设色(无 CFS 料道数据时手动匹配)
const PRESET_COLORS = [
  { c: '#1A1A1A', n: '黑' }, { c: '#F2F2F2', n: '白' }, { c: '#8C8C8C', n: '灰' },
  { c: '#D32F2F', n: '红' }, { c: '#F57C00', n: '橙' }, { c: '#FBC02D', n: '黄' },
  { c: '#388E3C', n: '绿' }, { c: '#1976D2', n: '蓝' }, { c: '#7B1FA2', n: '紫' },
  { c: '#795548', n: '棕' },
]
const selectedColorName = computed(() => {
  if (pickedSlot.value)
    return `CFS ${pickedSlot.value.box}${pickedSlot.value.slot} · `
      + (pickedSlot.value.name || pickedSlot.value.material || '已装料')
  const c = (color.value || '').toLowerCase()
  const p = PRESET_COLORS.find((x) => x.c.toLowerCase() === c)
  return p ? p.n : '自定义'
})

// CFS 料道(真实颜色/材质,Moonraker box 对象直读)
const cfsSlots = computed(() => {
  const out = []
  for (const b of cfsInfo.value?.boxes || []) {
    (b.slots || []).forEach((s, i) => {
      if (s.color) out.push({ ...s, index: s.index || i + 1, box: b.box })
    })
  }
  return out
})
const hasCfs = computed(() => cfsSlots.value.length > 0)

const pickedSlot = ref(null)   // 当前选中的 CFS 槽位对象

// 耗材材质跟随 CFS 槽位:先精确匹配产品名(如 Soleyin Basic PETG → 同名官方档),
// 匹配不到再按材质类型回退(PETG → CR-PETG)。免密通道只有类型,配 SSH 密码才有产品名
function syncFilamentToSlot() {
  const s = pickedSlot.value
  if (!s) return
  const name = String(s.name || '').trim()
  const fil = filaments.value
  if (!fil.length) return
  let f
  if (name) {
    const n = name.toLowerCase()
    f = fil.find((x) => (x.name || '').toLowerCase() === n)
      || fil.find((x) => (x.name || '').toLowerCase().includes(n))
  }
  if (!f && s.material)
    f = fil.find((x) => (x.type || '').toUpperCase().includes(s.material.toUpperCase()))
  if (f) filamentId.value = f.id
}

function pickCfsSlot(s) {
  pickedSlot.value = s
  color.value = s.color
  cfsTnn.value = s.slot   // 槽号已含盒号(如 T1A),直接用作换料指令的 TNN
  syncFilamentToSlot()
}

function pickPreset(c) {
  pickedSlot.value = null
  color.value = c.c
  cfsTnn.value = ''   // 手动预设色:不指定料道
}

// CFS 料道或切片耗材列表就绪后:默认选中第一个槽位;选项晚到时重新同步材质
watch([cfsSlots, filaments], () => {
  if (!hasCfs.value) return
  if (!pickedSlot.value || !cfsSlots.value.includes(pickedSlot.value))
    pickCfsSlot(cfsSlots.value[0])
  else syncFilamentToSlot()
})

const colorHint = computed(() => {
  if (hasCfs.value)
    return '✅ 已同步 CFS 实时装料:颜色/槽位/材质来自打印机,切片配色与换料自动一致'
  if (!cfsInfo.value || cfsInfo.value.available === false)
    return '常见耗材预设色;切片配色写入 G-code,实际供料由打印机当前装料决定'
  return '检测到 CFS 但未读到装料槽位;打印将使用打印机当前装料料道'
})

function pickDefaults() {
  if (!bundle.value) return
  if (props.nozzleHint && nozzles.value.some((n) => n.nozzle === props.nozzleHint)) {
    nozzle.value = props.nozzleHint
    return
  }
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
  if (props.materialHint) {
    const f = fil.find((x) => (x.type || '').toUpperCase().includes(props.materialHint))
    if (f) {
      filamentId.value = f.id
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

// 材质期望变化(父页切换模型版本)→ 重新匹配耗材档
watch(() => props.materialHint, () => {
  if (props.materialHint && !pickedSlot.value) ensureDefaults()
})

// 换打印机 → 机型/参数包/CFS 状态联动
watch(printerId, async () => {
  pickDefaults()
  cfsInfo.value = null
  pickedSlot.value = null
  cfsTnn.value = ''
  if (printerId.value) {
    try { cfsInfo.value = await api.get(`/api/printers/${printerId.value}/cfs`) }
    catch { cfsInfo.value = null }
  }
})

// 机型/喷嘴变化 → 拉取对应耗材工艺
watch([bundle, nozzle], () => loadOptions())

onMounted(async () => {
  try {
    const [ps, pr] = await Promise.all([api.get('/api/printers'), api.get('/api/profiles')])
    printers.value = ps
    profiles.value = pr
    if (ps.length) printerId.value = ps[0].id
  } catch { /* 弹层内校验兜底 */ }
})

async function submit() {
  if (submitting.value) return
  if (!printerId.value) return showFailToast('请先到「打印机」页添加打印机')
  if (!bundle.value) return showFailToast('打印机未设置机型:请到「打印机→编辑」选择')
  if (!machineId.value) return showFailToast('请选择喷嘴直径')
  if (!filamentId.value) return showFailToast('请选择耗材材质')
  submitting.value = true
  try {
    const res = await api.post('/api/jobs/oneclick', {
      ...props.basePayload,
      printer_id: printerId.value,
      bundle: bundle.value.key,
      machine_id: machineId.value,
      filament_ids: [filamentId.value],
      filament_colors: [color.value],
      process_id: processId.value,
      cfs_tnn: cfsTnn.value || null,
      auto_start: autoStart.value,
    })
    emit('update:show', false)
    emit('submitted', res.job_id)
  } catch (e) {
    showFailToast(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <van-popup :show="show" position="bottom" round style="padding:16px;max-height:85%;overflow-y:auto"
             @update:show="emit('update:show', $event)">
    <h3 class="pb-title">{{ title }}</h3>
    <van-cell title="打印机" is-link
              :value="printer?.name || '请先添加打印机'"
              @click="!printers.length && emit('update:show', false)" />
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
          <!-- 有 CFS:只显示真实料道(带槽位号与材质角标);无 CFS:显示常见耗材预设色 -->
          <template v-if="hasCfs">
            <span v-for="s in cfsSlots" :key="s.box + s.slot" class="pb-slot"
                  :title="`CFS 料道${s.box}${s.slot} · ${s.name || s.material}`"
                  @click="pickCfsSlot(s)">
              <span class="pb-dot" :class="{ active: pickedSlot && pickedSlot.box === s.box && pickedSlot.slot === s.slot }"
                    :style="{ background: s.color }">
                <span class="pb-slotnum">{{ s.box.replace('T', '') }}{{ 'ABCD'[s.index - 1] || s.index }}</span>
              </span>
              <span class="pb-slotmat">{{ s.material || '已装料' }}</span>
            </span>
          </template>
          <template v-else>
            <span v-for="c in PRESET_COLORS" :key="c.c" class="pb-dot"
                  :class="{ active: color.toLowerCase() === c.c }"
                  :style="{ background: c.c }" :title="c.n" @click="pickPreset(c)"></span>
          </template>
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
    <div v-if="cfsTnn" class="pb-muted" style="padding:0 16px 4px">
      🎯 打印前将自动换料到 CFS 料道 <b>{{ cfsTnn }}</b>(与屏幕「进料」同一流程,约 20-60 秒)
    </div>
    <van-cell title="切片后自动开始打印">
      <template #right-icon>
        <van-switch v-model="autoStart" size="22" />
      </template>
    </van-cell>
    <van-button type="primary" block round style="margin-top:10px"
                :disabled="!printerId || submitting" @click="submit">
      {{ submitting ? '提交中...' : '开始下载并切片' }}
    </van-button>
    <div v-if="!printers.length" class="pb-muted" style="text-align:center;margin-top:8px">
      还没有打印机,请到「打印机」页添加
    </div>
  </van-popup>
</template>

<style scoped>
.pb-select { width: 100%; border: 1px solid #ebedf0; border-radius: 6px; padding: 4px 8px; }
.pb-colors { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.pb-dot {
  width: 26px; height: 26px; border-radius: 50%; cursor: pointer;
  border: 2px solid #fff; box-shadow: 0 0 0 1px #dcdee0; display: inline-flex;
  align-items: center; justify-content: center;
}
.pb-dot.active { box-shadow: 0 0 0 2px var(--pb-primary); }
.pb-slot {
  display: inline-flex; flex-direction: column; align-items: center;
  gap: 2px; cursor: pointer;
}
.pb-slotmat { font-size: 9px; color: #969799; line-height: 1; }
.pb-slotnum {
  font-size: 10px; color: #fff; text-shadow: 0 0 2px #000; font-weight: 700;
}
</style>
