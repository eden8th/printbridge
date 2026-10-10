import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/search' },
  { path: '/search', component: () => import('./views/Search.vue'), meta: { title: '发现' } },
  { path: '/model/:source/:id', component: () => import('./views/ModelDetail.vue'), meta: { title: '模型详情' } },
  { path: '/library', component: () => import('./views/Library.vue'), meta: { title: '我的模型库' } },
  { path: '/printers', component: () => import('./views/Printers.vue'), meta: { title: '打印机' } },
  { path: '/printers/:id', component: () => import('./views/PrinterDetail.vue'), meta: { title: '打印机详情' } },
  { path: '/jobs', component: () => import('./views/Jobs.vue'), meta: { title: '打印任务' } },
  { path: '/jobs/:id', component: () => import('./views/JobDetail.vue'), meta: { title: '任务详情' } },
  { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: '设置' } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} · PrintBridge`
})
export default router
