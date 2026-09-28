import { onBeforeUnmount, onMounted, ref } from 'vue'

const isMobile = ref(window.innerWidth < 768)
let count = 0

function update() {
  isMobile.value = window.innerWidth < 768
}

/** 响应式设备判断:< 768px 视为移动端(H5)。多页面共享一个监听。 */
export function useIsMobile() {
  onMounted(() => {
    if (count === 0) window.addEventListener('resize', update)
    count += 1
  })
  onBeforeUnmount(() => {
    count -= 1
    if (count === 0) window.removeEventListener('resize', update)
  })
  return isMobile
}
