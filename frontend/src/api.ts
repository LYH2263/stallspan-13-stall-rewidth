export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    // FastAPI 的错误体是 {detail: ...}，提取成人话给页面提示
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body)
    } catch { /* 非 JSON 错误体就用 statusText */ }
    throw new Error(msg)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
