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
        <div class="pb-brand-logo">🖨️</div>
        <div>
          <div class="pb-brand-text">PrintBridge</div>
          <div class="pb-brand-sub">3D 跨品牌一键打印平台</div>
        </div>
      </div>

      <nav class="pb-navlinks">
        <router-link v-for="t in tabs" :key="t.path" :to="t.path" custom
                     v-slot="{ navigate, isActive }">
          <span class="pb-navlink" :class="{ active: isActive }" @click="navigate">
            <van-icon :name="t.icon" /> {{ t.label }}
          </span>
        </router-link>
      </nav>

      <div class="pb-topnav-right">
        <!-- 实时连接指示 -->
        <div class="pb-topnav-status" :title="store.wsConnected ? '实时通信正常' : '实时连接断开'">
          <span class="pb-wsdot" :class="{ ok: store.wsConnected }"></span>
          <span class="pb-wstext">{{ store.wsConnected ? '实时就绪' : '断开' }}</span>
        </div>
      </div>
    </div>
  </header>

  <main class="pb-main-body">
    <router-view />
  </main>

  <van-tabbar v-if="isMobile" route fixed>
    <van-tabbar-item v-for="t in tabs" :key="t.path" :to="t.path" :icon="t.icon">
      {{ t.label }}
    </van-tabbar-item>
  </van-tabbar>
</template>

<style scoped>
.pb-topnav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid #e2e8f0;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
}
.pb-topnav-inner {
  max-width: 1240px; margin: 0 auto; padding: 0 24px;
  height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 24px;
}
.pb-brand {
  cursor: pointer; display: flex; align-items: center; gap: 10px; user-select: none;
}
.pb-brand-logo {
  font-size: 22px; width: 38px; height: 38px;
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  border: 1px solid #bfdbfe;
  border-radius: 10px; display: flex; align-items: center; justify-content: center;
}
.pb-brand-text {
  font-size: 16px; font-weight: 700; color: #0f172a; line-height: 1.2;
}
.pb-brand-sub {
  font-size: 10px; color: #64748b; font-weight: 500;
}

.pb-navlinks { display: flex; gap: 6px; }
.pb-navlink {
  padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px;
  font-weight: 500; color: #475569; display: inline-flex; align-items: center; gap: 6px;
  transition: all 0.15s ease; user-select: none;
}
.pb-navlink:hover { background: #f1f5f9; color: #0f172a; }
.pb-navlink.active {
  background: #2563eb; color: #ffffff; font-weight: 600;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.pb-topnav-right {
  display: flex; align-items: center; gap: 16px;
}

.pb-topnav-status {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #64748b;
  background: #f8fafc; padding: 4px 10px; border-radius: 20px; border: 1px solid #e2e8f0;
}
.pb-wsdot {
  width: 8px; height: 8px; border-radius: 50%; background: #ef4444; display: block;
}
.pb-wsdot.ok {
  background: #16a34a; box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.2);
}
.pb-wstext { font-weight: 500; }

.pb-main-body {
  min-height: calc(100vh - 62px);
}
</style>
