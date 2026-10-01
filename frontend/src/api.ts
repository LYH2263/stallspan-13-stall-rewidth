export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text()
    // 保留 HTTP 状态码，供 isNotFound 等分支判断（错误文本仍可被 errDetail 解析）
    throw Object.assign(new Error(body || res.statusText), { status: res.status })
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

/** 从后端错误体里取中文 detail；解析不出时回退原始文本。 */
export function errDetail(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.detail === 'string') return parsed.detail
  } catch {
    /* 非 JSON 原样返回 */
  }
  return raw
}

/** 判断是否为 404（用于 latest 无确认记录的空态分支）。 */
export function isNotFound(e: unknown): boolean {
  return typeof e === 'object' && e !== null && (e as { status?: number }).status === 404
}
