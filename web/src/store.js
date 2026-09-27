import { reactive } from 'vue'

/** 全局实时状态:单一 WS 连接,任务/打印机事件分发到页面。 */
export const store = reactive({
  wsConnected: false,
  jobs: {},          // id -> job
  printers: {},      // id -> telemetry
  _ws: null,
  _listeners: [],

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
          this.jobs[msg.data.id] = { ...(this.jobs[msg.data.id] || {}), ...msg.data }
          this._emit('job', msg.data)
        } else if (msg.type === 'printer_telemetry') {
          this.printers[msg.data.printer_id] = msg.data
          this._emit('telemetry', msg.data)
        } else if (msg.type === 'library_update') {
          this._emit('library', msg.data)
        }
      } catch { /* 忽略坏帧 */ }
    }
    this._ws = ws
  },

  on(fn) { this._listeners.push(fn) },
  off(fn) { this._listeners = this._listeners.filter((f) => f !== fn) },
  _emit(type, data) { this._listeners.forEach((f) => f(type, data)) },
})
