const BASE = '/admin-api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
    this.name = 'ApiError'
  }
}

function getToken(): string | null {
  return sessionStorage.getItem('nav_admin_token')
}

export function setToken(t: string | null): void {
  if (t) sessionStorage.setItem('nav_admin_token', t)
  else sessionStorage.removeItem('nav_admin_token')
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (res.status === 204) return undefined as T
  if (!res.ok) {
    const detail = await res.text()
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export type ModelSpec = {
  id: string
  module: 'ollama' | 'openai'
  endpoint: string
  model: string
  context_window: number
  max_output_tokens: number
  label: string
  api_key_env: string | null
  enabled: boolean
}

export type Defaults = { chat: string; finalize: string }

export const api = {
  health: () => request<{ ok: boolean; models: number }>('/health'),
  models: {
    list: () => request<ModelSpec[]>('/models'),
    get: (id: string) =>
      request<ModelSpec>(`/models/${encodeURIComponent(id)}`),
    put: (id: string, body: ModelSpec) =>
      request<ModelSpec>(`/models/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      request<void>(`/models/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }),
    defaults: () => request<Defaults>('/models/defaults'),
    setDefaults: (body: Partial<Defaults>) =>
      request<Defaults>('/models/defaults', {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
  },
}