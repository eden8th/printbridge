import { reactive } from 'vue'

/** 全局实时状态:单一 WS 连接,任务/打印机事件分发到页面。 */
export const store = reactive({
  wsConnected: false,
  jobs: {},          // id -> job
  printers: {},      // id -> telemetry
  _ws: null,
  _listeners: [],

  // 桌面通知(打印完成/失败时);权限在首次用户点击时按需申请
  _notify(title, body) {
    if (typeof window === 'undefined' || !('Notification' in window)) return
    if (Notification.permission !== 'granted') return
    try { new Notification(title, { body }) } catch { /* 部分环境不支持构造 */ }
  },

  _notifyJob(prev, job) {
    const prevPrint = prev?.result?.print_status
    const nowPrint = job.result?.print_status
    if (nowPrint && nowPrint !== prevPrint && nowPrint !== 'in_progress') {
      const ok = nowPrint === 'completed'
      this._notify(
        ok ? '✅ 打印完成' : `⚠️ 打印${nowPrint === 'error' ? '出错' : '中断'}`,
        `${job.result.print_diagnosis || ''}(任务 #${job.id})`)
    } else if (job.state === 'failed' && prev?.state !== 'failed') {
      this._notify(`❌ 任务 #${job.id} 失败`, job.error || '详情见任务页')
    }
  },

  connect() {
    if (this._ws && this._ws.readyState <= 1) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/events`)
    ws.onopen = () => { this.wsConnected = true }
    ws.onclose = () => {
      this.wsConnected = false
      setTimeout(() => this.connect(), 3000)
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'job_update') {
          const prev = this.jobs[msg.data.id]
          this.jobs[msg.data.id] = { ...(prev || {}), ...msg.data }
          this._notifyJob(prev, msg.data)
          this._emit('job', msg.data)
        } else if (msg.type === 'job_deleted') {
          delete this.jobs[msg.data.id]
          this._emit('job', { id: msg.data.id, deleted: true })
        } else if (msg.type === 'jobs_batch_deleted') {
          (msg.data.ids || []).forEach((id) => { delete this.jobs[id] })
          this._emit('job', { batch: true })
        } else if (msg.type === 'printer_telemetry') {
          this.printers[msg.data.printer_id] = msg.data
          this._emit('telemetry', msg.data)
        } else if (msg.type === 'library_update') {
          this._emit('library', msg.data)
        }
      } catch { /* 忽略坏帧 */ }
    }
    this._ws = ws
    // 首次用户交互时申请通知权限(浏览器要求手势上下文)
    if (typeof document !== 'undefined' && 'Notification' in window
        && Notification.permission === 'default') {
      document.addEventListener('click', () => {
        Notification.requestPermission().catch(() => {})
      }, { once: true })
    }
  },

  on(fn) { this._listeners.push(fn) },
  off(fn) { this._listeners = this._listeners.filter((f) => f !== fn) },
  _emit(type, data) { this._listeners.forEach((f) => f(type, data)) },
})
