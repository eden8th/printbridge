<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { store } from './store'

const route = useRoute()
const router = useRouter()

onMounted(() => store.connect())

const tabs = [
  { path: '/search', label: '发现', icon: 'search' },
  { path: '/library', label: '模型库', icon: 'apps-o' },
  { path: '/printers', label: '打印机', icon: 'printer' },
  { path: '/jobs', label: '任务', icon: 'orders-o' },
  { path: '/settings', label: '设置', icon: 'setting-o' },
]
</script>

<template>
  <router-view />
  <van-tabbar route fixed placeholder-safe>
    <van-tabbar-item v-for="t in tabs" :key="t.path" :to="t.path" :icon="t.icon">
      {{ t.label }}
    </van-tabbar-item>
  </van-tabbar>
</template>
