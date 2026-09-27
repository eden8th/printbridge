const BASE = ''

async function request(method, url, body) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(BASE + url, opts)
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const data = await resp.json()
      detail = data.detail || data.error || detail
    } catch { /* 非 JSON 错误体 */ }
    throw new Error(detail)
  }
  if (resp.status === 204) return null
  return resp.json()
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body),
  del: (url) => request('DELETE', url),
}

/** 上传文件(multipart) */
export async function uploadFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  const resp = await fetch('/api/library/upload', { method: 'POST', body: fd })
  if (!resp.ok) throw new Error(`上传失败 HTTP ${resp.status}`)
  return resp.json()
}
