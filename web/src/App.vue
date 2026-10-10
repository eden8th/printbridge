<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { store } from './store'
import { useIsMobile } from './composables/useDevice'

const router = useRouter()
const isMobile = useIsMobile()

onMounted(() => {
  store.connect()
})

const tabs = computed(() => [
  { path: '/search', label: '发现', icon: 'search' },
  { path: '/library', label: '模型库', icon: 'apps-o' },
  { path: '/printers', label: '打印机', icon: 'printer' },
  { path: '/jobs', label: '任务', icon: 'orders-o' },
  { path: '/settings', label: '设置', icon: 'setting-o' },
])
</script>

<template>
  <header v-if="!isMobile" class="pb-topnav">
    <div class="pb-topnav-inner">
      <div class="pb-brand" @click="router.push('/search')">
        <span class="pb-brand-icon">🖨️</span> PrintBridge
        <span class="pb-brand-sub">跨品牌一键打印</span>
      </div>
      <nav class="pb-navlinks">
        <router-link v-for="t in tabs" :key="t.path" :to="t.path" custom
                     v-slot="{ navigate, isActive }">
          <span class="pb-navlink" :class="{ active: isActive }" @click="navigate">
            <van-icon :name="t.icon" /> {{ t.label }}
          </span>
        </router-link>
      </nav>
      <div class="pb-topnav-status" :title="store.wsConnected ? '实时连接正常' : '实时连接断开'">
        <span class="pb-wsdot" :class="{ ok: store.wsConnected }"></span>
      </div>
    </div>
  </header>

  <router-view />

  <van-tabbar v-if="isMobile" route fixed>
    <van-tabbar-item v-for="t in tabs" :key="t.path" :to="t.path" :icon="t.icon">
      {{ t.label }}
    </van-tabbar-item>
  </van-tabbar>
</template>

<style scoped>
.pb-topnav {
  position: sticky; top: 0; z-index: 100;
  background: #fff; border-bottom: 1px solid #eef0f3;
  box-shadow: 0 1px 8px rgba(16,24,40,.04);
}
.pb-topnav-inner {
  max-width: 1140px; margin: 0 auto; padding: 0 24px;
  height: 58px; display: flex; align-items: center; gap: 28px;
}
.pb-brand {
  font-size: 17px; font-weight: 700; cursor: pointer; display: flex;
  align-items: center; gap: 6px; color: #1a1a1a; white-space: nowrap;
}
.pb-brand-icon { font-size: 20px; }
.pb-brand-sub { font-size: 11px; color: #969799; font-weight: 400; margin-left: 2px; }
.pb-navlinks { display: flex; gap: 4px; flex: 1; }
.pb-navlink {
  padding: 7px 16px; border-radius: 20px; cursor: pointer; font-size: 14px;
  color: #4b5563; display: inline-flex; align-items: center; gap: 5px;
  transition: background .15s, color .15s; user-select: none;
}
.pb-navlink:hover { background: #f3f4f6; color: #1a1a1a; }
.pb-navlink.active { background: #e8f1ff; color: var(--pb-primary); font-weight: 600; }
.pb-topnav-status { display: flex; align-items: center; }
.pb-wsdot {
  width: 9px; height: 9px; border-radius: 50%; background: #ee0a24; display: block;
}
.pb-wsdot.ok { background: #07c160; box-shadow: 0 0 0 3px rgba(7,193,96,.15); }
</style>
