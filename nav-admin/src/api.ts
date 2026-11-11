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

// ── Types ────────────────────────────────────────────────

export type Page<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
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

export type Defaults = { chat: string; finalize: string; translate: string }

export type Phone = {
  id: string
  number: string
  type: string | null
  extension: string | null
  language: string | null
  description: string | null
}

export type PhoneInput = Omit<Phone, 'id'>

export type Organization = {
  id: string
  name: string
  alternate_name: string | null
  description: string
  email: string | null
  website: string | null
  legal_status: string | null
  year_incorporated: number | null
  logo: string | null
  uri: string | null
  parent_organization_id: string | null
  created_at: string
  updated_at: string
  phones: Phone[]
}

export type OrganizationInput = Omit<
  Organization,
  'id' | 'created_at' | 'updated_at' | 'phones'
>

export type OrgOption = { id: string; name: string }

export type LocationWithCount = {
  id: string
  name: string | null
  alternate_name: string | null
  description: string | null
  address: string | null
  latitude: string | null
  longitude: string | null
  service_count: number
  phones: Phone[]
}

export type LocationInput = {
  organization_id: string | null
  name: string | null
  alternate_name: string | null
  description: string | null
  address: string | null
  latitude: string | number | null
  longitude: string | number | null
}

export type Location = Omit<LocationInput, 'organization_id'> & {
  id: string
  organization_id: string | null
  created_at: string
  updated_at: string
}

export type LocationSearchRow = {
  id: string
  name: string | null
  alternate_name: string | null
  description: string | null
  address: string | null
  latitude: number | null
  longitude: number | null
  organization_id: string | null
  organization_name: string | null
  service_count: number
  distance_km: number | null
}

export type Service = {
  id: string
  organization_id: string
  name: string
  alternate_name: string | null
  description: string | null
  url: string | null
  email: string | null
  status: 'active' | 'inactive' | 'defunct' | 'temporarily closed'
  interpretation_services: string | null
  application_process: string | null
  fees_description: string | null
  eligibility_description: string | null
  minimum_age: string | number | null
  maximum_age: string | number | null
  assured_date: string | null
  alert: string | null
  last_modified: string | null
  created_at: string
  updated_at: string
  phones: Phone[]
}

export type ServiceInput = Omit<
  Service,
  'id' | 'organization_id' | 'created_at' | 'updated_at' | 'phones'
>

export type GeocodeSuggestion = {
  lat: number
  lng: number
  display_name: string
  postcode: string | null
  city: string | null
}

export type PromptNearby = {
  radius_km: number
  location_limit: number
  index_limit: number
}

export type PromptState = {
  chat_prompt: string
  finalize_prompt: string
  nearby: PromptNearby
  defaults: {
    chat_prompt: string
    finalize_prompt: string
    nearby: PromptNearby
  }
  overridden: { chat: boolean; finalize: boolean; nearby: boolean }
}

export type TokenStatus = {
  configured: boolean
  source: 'env' | 'database' | 'none'
}

export type LanguageCoverage = {
  locale: string
  translated: number
  total: number
}

export type UiStringRow = {
  key: string
  english: string
  context: string | null
  translated: string | null
  translator_signature: string | null
  translated_at: string | null
}

export type TranslationJob = {
  id: string
  mode: 'missing' | 'refresh'
  locale: string | null
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  total: number
  done: number
  failed: number
  cancel_requested: boolean
  error_summary: string | null
  created_at: string
}

// ── API ──────────────────────────────────────────────────

export const api = {
  health: () => request<{ ok: boolean; models: number }>('/health'),

  auth: {
    status: () => request<TokenStatus>('/auth/status'),
    changeToken: (
      current_token: string,
      new_token: string,
      confirm_token: string,
    ) =>
      request<{ ok: boolean }>('/auth/token', {
        method: 'PUT',
        body: JSON.stringify({ current_token, new_token, confirm_token }),
      }),
  },

  models: {
    list: () => request<ModelSpec[]>('/models'),
    get: (id: string) => request<ModelSpec>(`/models/${encodeURIComponent(id)}`),
    put: (id: string, body: ModelSpec) =>
      request<ModelSpec>(`/models/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      request<void>(`/models/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    defaults: () => request<Defaults>('/models/defaults'),
    setDefaults: (body: Partial<Defaults>) =>
      request<Defaults>('/models/defaults', {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
  },

  prompt: {
    state: () => request<PromptState>('/prompt'),
    setChat: (text: string) =>
      request<{ ok: boolean }>('/prompt/chat', {
        method: 'PUT',
        body: JSON.stringify({ text }),
      }),
    setFinalize: (text: string) =>
      request<{ ok: boolean }>('/prompt/finalize', {
        method: 'PUT',
        body: JSON.stringify({ text }),
      }),
    setNearby: (params: PromptNearby) =>
      request<{ ok: boolean }>('/prompt/nearby', {
        method: 'PUT',
        body: JSON.stringify(params),
      }),
    reset: (section: 'chat' | 'finalize' | 'nearby') =>
      request<void>(`/prompt/${section}`, { method: 'DELETE' }),
  },

  geocodeSearch: (q: string, signal?: AbortSignal) =>
    request<GeocodeSuggestion[]>(`/geocode/search?q=${encodeURIComponent(q)}`, {
      signal,
    }),

  languages: {
    coverage: () => request<LanguageCoverage[]>('/languages/coverage'),
    uiStrings: (locale: string) =>
      request<UiStringRow[]>(
        `/ui-strings?locale=${encodeURIComponent(locale)}`,
      ),
    setTranslation: (key: string, locale: string, translated: string) =>
      request<{ ok: boolean }>(
        `/ui-strings/${encodeURIComponent(key)}/translations/${encodeURIComponent(locale)}`,
        { method: 'PUT', body: JSON.stringify({ translated }) },
      ),
    deleteTranslation: (key: string, locale: string) =>
      request<void>(
        `/ui-strings/${encodeURIComponent(key)}/translations/${encodeURIComponent(locale)}`,
        { method: 'DELETE' },
      ),
  },

  translations: {
    start: (mode: 'missing' | 'refresh', locale?: string | null) =>
      request<TranslationJob>('/translations/run', {
        method: 'POST',
        body: JSON.stringify({ mode, locale: locale ?? null }),
      }),
    active: () => request<TranslationJob[]>('/translations/active'),
    cancel: (jobId: string) =>
      request<{ ok: boolean }>(`/translations/${jobId}/cancel`, {
        method: 'POST',
      }),
  },

  directory: {
    orgs: {
      list: (page: number, pageSize = 50) =>
        request<Page<Organization>>(
          `/organizations?page=${page}&page_size=${pageSize}`,
        ),
      create: (body: OrganizationInput) =>
        request<Organization>('/organizations', {
          method: 'POST',
          body: JSON.stringify(body),
        }),
      update: (id: string, body: OrganizationInput) =>
        request<Organization>(`/organizations/${id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
      remove: (id: string) =>
        request<void>(`/organizations/${id}`, { method: 'DELETE' }),
      options: () => request<OrgOption[]>('/organizations/options'),
    },
    locations: {
      listForOrg: (orgId: string) =>
        request<LocationWithCount[]>(`/organizations/${orgId}/locations`),
      create: (orgId: string, body: LocationInput) =>
        request<Location>(`/organizations/${orgId}/locations`, {
          method: 'POST',
          body: JSON.stringify(body),
        }),
      createGlobal: (body: LocationInput) =>
        request<Location>('/locations', {
          method: 'POST',
          body: JSON.stringify(body),
        }),
      update: (id: string, body: LocationInput) =>
        request<Location>(`/locations/${id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
      remove: (id: string) =>
        request<void>(`/locations/${id}`, { method: 'DELETE' }),
      get: (id: string) => request<Location>(`/locations/${id}`),
      search: (params: {
        q?: string
        lat?: number
        lng?: number
        radius_km?: number
        page?: number
        page_size?: number
      }) => {
        const p = new URLSearchParams()
        if (params.q) p.set('q', params.q)
        if (params.lat !== undefined) p.set('lat', String(params.lat))
        if (params.lng !== undefined) p.set('lng', String(params.lng))
        if (params.radius_km !== undefined)
          p.set('radius_km', String(params.radius_km))
        if (params.page !== undefined) p.set('page', String(params.page))
        if (params.page_size !== undefined)
          p.set('page_size', String(params.page_size))
        return request<Page<LocationSearchRow>>(`/locations?${p.toString()}`)
      },
    },
    services: {
      listForLoc: (locId: string) =>
        request<Service[]>(`/locations/${locId}/services`),
      create: (locId: string, body: ServiceInput) =>
        request<Service>(`/locations/${locId}/services`, {
          method: 'POST',
          body: JSON.stringify(body),
        }),
      update: (id: string, body: ServiceInput) =>
        request<Service>(`/services/${id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
      remove: (id: string) =>
        request<void>(`/services/${id}`, { method: 'DELETE' }),
    },
    phones: {
      create: (
        ownerType: 'org' | 'loc' | 'svc',
        ownerId: string,
        body: PhoneInput,
      ) =>
        request<Phone>(`/phones/${ownerType}/${ownerId}`, {
          method: 'POST',
          body: JSON.stringify(body),
        }),
      update: (id: string, body: PhoneInput) =>
        request<Phone>(`/phones/${id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
      remove: (id: string) =>
        request<void>(`/phones/${id}`, { method: 'DELETE' }),
    },
  },

  backup: {
    exportDatabase: async () => {
      const token = getToken()
      const res = await fetch(`${BASE}/database/export`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new ApiError(res.status, await res.text())
      const blob = await res.blob()
      const cd = res.headers.get('content-disposition') ?? ''
      const match = cd.match(/filename="([^"]+)"/)
      const filename = match?.[1] ?? 'navigator-backup.json'
      return { blob, filename }
    },
    importDatabase: async (file: File) => {
      const token = getToken()
      const form = new FormData()
      form.append('file', file)
      form.append('mode', 'replace')
      const res = await fetch(`${BASE}/database/import`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      if (!res.ok) throw new ApiError(res.status, await res.text())
      return res.json() as Promise<{
        ok: boolean
        counts: Record<string, number>
      }>
    },
  },
}