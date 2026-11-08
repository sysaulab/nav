const BASE = '/api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
    this.name = 'ApiError'
  }
}

export function isSessionError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  const d = err.detail.toLowerCase()
  return (
    err.status === 410 ||
    d.includes('session expired') ||
    d.includes('session has ended') ||
    (err.status === 404 && d.includes('session not found'))
  )
}

type RequestListener = (sentAtMs: number) => void
let requestListeners: RequestListener[] = []

export function onRequest(fn: RequestListener): () => void {
  requestListeners.push(fn)
  return () => {
    requestListeners = requestListeners.filter((f) => f !== fn)
  }
}

function notifyRequestSent() {
  const t = Date.now()
  for (const f of requestListeners) {
    try { f(t) } catch { /* ignore */ }
  }
}

async function parseError(res: Response): Promise<Error> {
  const detail = await res.text()
  return new ApiError(res.status, detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  notifyRequestSent()
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (res.status === 204) return undefined as T
  if (!res.ok) throw await parseError(res)
  return res.json() as Promise<T>
}

function uploadMultipart<T>(
  path: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}${path}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status === 204) return resolve(undefined as T)
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T)
        } catch (e) {
          reject(new Error(`invalid JSON response: ${e}`))
        }
      } else {
        reject(new ApiError(xhr.status, xhr.responseText))
      }
    }
    xhr.onerror = () => reject(new Error('network error'))
    const body = new FormData()
    body.append('file', file)
    notifyRequestSent()
    xhr.send(body)
  })
}

async function streamNdjson(
  path: string,
  messages: import('./types').ChatMessage[],
  onChunk: (obj: unknown) => void,
): Promise<void> {
  notifyRequestSent()
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
  if (!res.ok) throw await parseError(res)
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop()!
    for (const line of lines) {
      if (!line.trim()) continue
      try {
        onChunk(JSON.parse(line))
      } catch { /* skip malformed line */ }
    }
  }
}

export const api = {
  geocode: (q: string) =>
    request<{ lat: number; lng: number; display_name: string | null } | null>(
      `/geocode?q=${encodeURIComponent(q)}`,
    ),
  geocodeSearch: (q: string, signal?: AbortSignal) =>
    request<import('./types').GeocodeSuggestion[]>(
      `/geocode/search?q=${encodeURIComponent(q)}`,
      { signal },
    ),
  health: {
    maestro: () =>
      request<{ status: string; service: string; version: string }>('/health'),
    ingest: () =>
      request<{ ok: boolean; endpoint: string; error?: string }>('/health/ingest'),
    geocoder: () =>
      request<{ ok: boolean; endpoint: string; error?: string }>('/health/geocoder'),
    ollama: () =>
      request<{ ok: boolean; endpoint: string; model: string; error?: string }>(
        '/health/ollama',
      ),
    sql: () =>
      request<{ ok: boolean; backend: string; error?: string }>('/health/sql'),
  },
  interviews: {
    createOrResume: () =>
      request<import('./types').InterviewSession>('/interviews', { method: 'POST' }),
    active: () =>
      request<import('./types').InterviewSession | null>('/interviews/active'),
    end: (sid: string) =>
      request<void>(`/interviews/${sid}`, { method: 'DELETE' }),
    location: (sid: string) =>
      request<import('./types').SessionLocation>(`/interviews/${sid}/location`),
    setLocation: (
      sid: string,
      payload: {
        postal_code: string
        lat?: number
        lng?: number
        display_name?: string | null
      },
    ) =>
      request<import('./types').SessionLocation>(`/interviews/${sid}/location`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    contextPrompt: (sid: string) =>
      request<import('./types').ContextPrompt>(`/interviews/${sid}/context-prompt`),
    documents: {
      list: (sid: string) =>
        request<import('./types').DocumentMeta[]>(`/interviews/${sid}/documents`),
      upload: (sid: string, file: File, onProgress?: (pct: number) => void) =>
        uploadMultipart<import('./types').DocumentMeta>(
          `/interviews/${sid}/documents`,
          file,
          onProgress,
        ),
      remove: (sid: string, did: string) =>
        request<void>(`/interviews/${sid}/documents/${did}`, { method: 'DELETE' }),
    },
    chat: (
      sid: string,
      messages: import('./types').ChatMessage[],
      onChunk: (obj: unknown) => void,
    ) => streamNdjson(`/interviews/${sid}/chat`, messages, onChunk),
    finalize: (
      sid: string,
      messages: import('./types').ChatMessage[],
      onChunk: (obj: unknown) => void,
    ) => streamNdjson(`/interviews/${sid}/finalize`, messages, onChunk),
  },
}