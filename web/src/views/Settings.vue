<script setup>
import { computed, onMounted, ref } from 'vue'
import { showSuccessToast } from 'vant'
import { api } from '../api'

const makerworldToken = ref('')
const hasToken = ref(false)
const region = ref('cn')
const slicerPath = ref('')
const slicerProbe = ref(null)
const settingsPath = ref(false)
const verifying = ref(false)
const verifyResult = ref('')
const mwAccount = ref('')
const mwPassword = ref('')
const loggingIn = ref(false)
const loginResult = ref('')
const openFaq = ref([])

// 方式二:书签脚本(在 makerworld.com 页面上读取 token 复制到剪贴板)
const bookmarklet = computed(() => {
  const code = `javascript:(()=>{try{const m=document.cookie.match(/(?:^|;\\s*)token=([^;]+)/);if(!m){alert('未找到 token,请确认已登录 makerworld.com');return}const t=decodeURIComponent(m[1]);(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>alert('token 已复制:'+t.slice(0,12)+'...,请回到 PrintBridge 粘贴')).catch(()=>{prompt('请手动复制 token:',t)})}catch(e){alert('读取失败:'+e.message)}})()`
  return code
})

async function mwLogin() {
  if (!mwAccount.value.trim() || !mwPassword.value) {
    loginResult.value = '请填写账号和密码'
    return
  }
  loggingIn.value = true
  try {
    const r = await api.post('/api/settings/makerworld-login', {
      account: mwAccount.value.trim(),
      password: mwPassword.value,
      region: region.value,
    })
    loginResult.value = (r.ok === true ? '✅ ' : r.ok === false ? '❌ ' : '⚠️ ') + r.detail
    if (r.ok === true) {
      hasToken.value = true
      mwPassword.value = ''
      showSuccessToast('拓竹凭证已自动保存')
    }
  } catch (e) {
    loginResult.value = e.message
  } finally {
    loggingIn.value = false
  }
}

async function verifyToken() {
  const token = makerworldToken.value.trim()
  if (!token) {
    verifyResult.value = '请先粘贴 token'
    return
  }
  verifying.value = true
  try {
    const r = await api.post('/api/settings/verify-makerworld', { token })
    verifyResult.value = r.valid === true ? '✅ ' + r.detail
      : r.valid === false ? '❌ ' + r.detail : '⚠️ ' + r.detail
  } catch (e) {
    verifyResult.value = e.message
  } finally {
    verifying.value = false
  }
}

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
        下载模型需要拓竹账号凭证。三种方式任选其一(推荐方式一)。
      </div>

      <!-- 方式一:账号密码登录 -->
      <div class="pb-method">
        <div class="pb-method-tag">方式一 · 推荐</div>
        <b>账号密码登录</b>(全自动,密码不保存)
        <van-field v-model="mwAccount" label="账号" placeholder="手机号 / 邮箱" clearable />
        <van-field v-model="mwPassword" label="密码" type="password" placeholder="拓竹账号密码"
                   clearable />
        <div style="margin:8px 16px" class="pb-row">
          <van-button type="primary" size="small" :loading="loggingIn" @click="mwLogin">
            登录并保存
          </van-button>
          <van-button size="small" plain :loading="verifying" @click="verifyToken">验证</van-button>
          <span v-if="loginResult" class="pb-muted">{{ loginResult }}</span>
        </div>
      </div>

      <!-- 方式二:书签脚本 -->
      <div class="pb-method">
        <div class="pb-method-tag">方式二</div>
        <b>一键提取书签</b>(账号触发验证码时用)
        <div class="pb-muted" style="margin:4px 0;line-height:1.6">
          ① 把下面的橙色按钮<b>拖到浏览器书签栏</b> →
          ② 打开并登录 <a href="https://makerworld.com" target="_blank" rel="noopener">makerworld.com</a> →
          ③ 点书签栏里的按钮 → token 自动复制 → 回这里粘贴保存
        </div>
        <a class="pb-bookmarklet" :href="bookmarklet"
           onclick="return false"
           title="拖我到书签栏">🔑 复制拓竹 Token</a>
        <van-field v-model="makerworldToken" label="token"
                   :placeholder="hasToken ? '已配置(输入新值可更换)' : '粘贴复制的 token'" />
      </div>

      <!-- 方式三:F12 -->
      <van-collapse v-model="openFaq">
        <van-collapse-item title="方式三 · F12 手动获取(备用)" name="f12">
          <div class="pb-muted" style="line-height:1.7">
            ① 电脑浏览器打开 makerworld.com 并登录<br />
            ② 按 <b>F12</b> 打开开发者工具,切到「应用程序 / Application」标签<br />
            ③ 左侧展开「Cookie」→ 点选 https://makerworld.com<br />
            ④ 找到名为 <b>token</b> 的行,复制它的值粘贴到上面
          </div>
        </van-collapse-item>
      </van-collapse>

      <van-field label="站点" readonly>
        <template #input>
          <van-radio-group v-model="region" direction="horizontal">
            <van-radio name="cn">国内站</van-radio>
            <van-radio name="com">国际站</van-radio>
          </van-radio-group>
        </template>
      </van-field>
      <div style="margin:8px 16px">
        <van-button type="primary" size="small" @click="saveMakerworld">保存手填内容</van-button>
        <span class="pb-muted" style="margin-left:8px">凭证只保存在你自己的设备上,平台不托管账号</span>
      </div>
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

<style scoped>
.pb-method {
  border: 1px solid #ebedf0; border-radius: 8px; padding: 10px 12px;
  margin-bottom: 10px; font-size: 13px; position: relative;
}
.pb-method-tag {
  position: absolute; top: -9px; left: 10px; background: #1989fa; color: #fff;
  font-size: 11px; padding: 1px 8px; border-radius: 8px;
}
.pb-bookmarklet {
  display: inline-block; background: linear-gradient(135deg, #ff9800, #ff5722);
  color: #fff; font-size: 13px; padding: 6px 14px; border-radius: 6px;
  text-decoration: none; margin: 6px 0; cursor: grab; border: 1px dashed #fff3e0;
  box-shadow: 0 1px 4px rgba(0,0,0,.2);
}
</style>
