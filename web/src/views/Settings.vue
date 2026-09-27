<script setup>
import { onMounted, ref } from 'vue'
import { showSuccessToast } from 'vant'
import { api } from '../api'

const makerworldToken = ref('')
const hasToken = ref(false)
const region = ref('cn')
const slicerPath = ref('')
const slicerProbe = ref(null)
const settingsPath = ref(false)

onMounted(async () => {
  const s = await api.get('/api/settings')
  region.value = s.makerworld.region || 'cn'
  hasToken.value = !!s.makerworld.token
  slicerPath.value = s.app.slicer_exe || ''
  slicerProbe.value = await api.get('/api/settings/slicer-probe')
})

async function saveMakerworld() {
  const body = { region: region.value }
  if (settingsPath.value || makerworldToken.value !== '') {
    body.token = makerworldToken.value || ''
  }
  await api.put('/api/settings', { makerworld: body })
  showSuccessToast('已保存')
  hasToken.value = !!makerworldToken.value || hasToken.value
  makerworldToken.value = ''
}

async function saveSlicer() {
  await api.put('/api/settings', { app: { slicer_exe: slicerPath.value } })
  slicerProbe.value = await api.get('/api/settings/slicer-probe')
  showSuccessToast(slicerProbe.value.found ? `已定位:${slicerProbe.value.path}` : '未找到,请填完整路径')
}
</script>

<template>
  <div class="pb-page">
    <van-nav-bar title="设置" />

    <div class="pb-card">
      <h3 class="pb-title">MakerWorld(拓竹)凭证</h3>
      <div class="pb-muted" style="margin-bottom:8px">
        浏览器登录 makerworld.com(或 makerworld.com.cn)后,F12 → Application →
        Cookies,复制 <b>token</b> 的值粘贴到这里。仅用于在你自己设备上拉取模型,
        平台不存储账号、不二次分发文件。
      </div>
      <van-field v-model="makerworldToken" label="token"
                 :placeholder="hasToken ? '已配置(输入新值可更换)' : '粘贴 Cookie 中的 token'" />
      <van-field label="站点" readonly>
        <template #input>
          <van-radio-group v-model="region" direction="horizontal">
            <van-radio name="cn">国内站</van-radio>
            <van-radio name="com">国际站</van-radio>
          </van-radio-group>
        </template>
      </van-field>
      <van-button type="primary" size="small" style="margin:8px 16px" @click="saveMakerworld">
        保存
      </van-button>
    </div>

    <div class="pb-card">
      <h3 class="pb-title">切片引擎</h3>
      <div class="pb-muted" style="margin-bottom:8px">
        支持本机安装的 Creality Print 或 OrcaSlicer 的无头命令行切片。
      </div>
      <van-field v-model="slicerPath" label="程序路径"
                 placeholder="留空自动检测,或填完整 exe 路径" />
      <van-button type="primary" size="small" style="margin:8px 16px" @click="saveSlicer">
        检测并保存
      </van-button>
      <div v-if="slicerProbe" class="pb-muted" style="margin:0 16px">
        {{ slicerProbe.found ? `✅ 已找到:${slicerProbe.path}` : '❌ 未找到切片器' }}
      </div>
    </div>

    <div class="pb-card">
      <h3 class="pb-title">关于</h3>
      <div class="pb-muted">
        PrintBridge v0.1.0(MVP)—— 跨品牌一键打印平台自托管版。<br />
        支持源:MakerWorld(拓竹) · 支持机型:创想 K 系列、Klipper/Moonraker 系。
      </div>
    </div>
  </div>
</template>
