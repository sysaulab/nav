import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type {
  Location, LocationIn,
  LocationServiceIn, LocationServiceOut,
  Organization, OrganizationIn,
  ServiceIn,
} from '../types'
import * as React from 'react'

// ─────────────────────────────────────────────────────────────
// Selection state carried up to the shell
// ─────────────────────────────────────────────────────────────
type SelOrg = { id: string; name: string } | null
type SelLoc = { id: string; name: string } | null

export default function Database() {
  const [org, setOrg] = useState<SelOrg>(null)
  const [loc, setLoc] = useState<SelLoc>(null)

  return (
    <main className="min-h-screen bg-slate-50 p-8">
      <div className="mx-auto max-w-6xl">
        <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
          ← Back
        </Link>

        <header className="mt-6 mb-6">
          <h1 className="text-3xl font-semibold text-slate-900">Manage resources</h1>
          <p className="mt-2 text-slate-600">
            Organizations → locations → services. A service always belongs to a location.
          </p>
        </header>

        <nav className="mb-6 flex flex-wrap items-center gap-1 text-sm">
          <Crumb active={!org} onClick={() => { setOrg(null); setLoc(null) }}>
            Organizations
          </Crumb>
          {org && (
            <>
              <Sep />
              <Crumb active={!!org && !loc} onClick={() => setLoc(null)}>
                {org.name}
              </Crumb>
            </>
          )}
          {loc && (
            <>
              <Sep />
              <Crumb active>{loc.name}</Crumb>
            </>
          )}
        </nav>

        {!org && <OrganizationsView onSelect={setOrg} />}
        {org && !loc && (
          <LocationsView
            org={org}
            onSelect={setLoc}
            onOrgRenamed={(name) => setOrg({ id: org.id, name })}
          />
        )}
        {org && loc && (
          <LocationDetailView
            org={org}
            loc={loc}
            onBack={() => setLoc(null)}
            onLocRenamed={(name) => setLoc({ id: loc.id, name })}
          />
        )}
      </div>
    </main>
  )
}

// ─────────────────────────────────────────────────────────────
// Shared primitives
// ─────────────────────────────────────────────────────────────
function Crumb({
  active, onClick, children,
}: {
  active?: boolean
  onClick?: () => void
  children: React.ReactNode
}) {
  if (active) return <span className="font-medium text-slate-900">{children}</span>
  return (
    <button onClick={onClick} className="text-slate-500 hover:text-slate-900">
      {children}
    </button>
  )
}

function Sep() {
  return <span className="text-slate-300">/</span>
}

function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let live = true
    loader()
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setErr(e.message))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, err, reload: () => setNonce((n) => n + 1) }
}

function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      {message}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  )
}

const input =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none'

// ─────────────────────────────────────────────────────────────
// View 1 — Organizations
// ─────────────────────────────────────────────────────────────
function OrganizationsView({ onSelect }: { onSelect: (o: { id: string; name: string }) => void }) {
  const { data, err, reload } = useLoad(() => api.organizations.list())
  const [draft, setDraft] = useState<OrganizationIn | null>(null)

  const empty: OrganizationIn = {
    name: '',
    alternate_name: null,
    description: '',
    email: null,
    website: null,
    legal_status: null,
    year_incorporated: null,
    logo: null,
    uri: null,
    parent_organization_id: null,
    extra: {},
  }

  async function save() {
    if (!draft) return
    // Build a clean OrganizationIn body. We must not echo back `id`,
    // `created_at`, or `updated_at` when editing — the backend model uses
    // extra="forbid" and will 422 otherwise.
    const body: OrganizationIn = {
      name: draft.name,
      alternate_name: draft.alternate_name,
      description: draft.description,
      email: draft.email,
      website: draft.website,
      legal_status: draft.legal_status,
      year_incorporated: draft.year_incorporated,
      logo: draft.logo,
      uri: draft.uri,
      parent_organization_id: draft.parent_organization_id,
      extra: draft.extra,
    }
    try {
      if ('id' in draft && typeof (draft as { id?: string }).id === 'string') {
        await api.organizations.update((draft as Organization).id, body)
      } else {
        await api.organizations.create(body)
      }
      setDraft(null)
      reload()
    } catch (e) {
      alert((e as Error).message)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Organizations</h2>
          <button
            onClick={() => setDraft({ ...empty })}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
          >
            New
          </button>
        </div>
        <ErrorBanner message={err} />
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {(data ?? []).map((o) => (
            <li key={o.id} className="flex items-center">
              <button
                onClick={() => onSelect({ id: o.id, name: o.name })}
                className="flex-1 px-4 py-3 text-left hover:bg-slate-50"
              >
                <div className="font-medium text-slate-900">{o.name || '(unnamed)'}</div>
                {o.description && (
                  <div className="line-clamp-1 text-sm text-slate-600">{o.description}</div>
                )}
                <div className="mt-0.5 font-mono text-[11px] text-slate-400">
                  {o.id.slice(0, 8)}
                </div>
              </button>
              <button
                onClick={() => setDraft(o)}
                className="px-3 py-3 text-xs text-slate-500 hover:text-slate-900"
              >
                Edit
              </button>
            </li>
          ))}
          {data && data.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-500">
              No organizations yet. Create one to get started.
            </li>
          )}
        </ul>
      </section>

      <section>
        {draft && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-medium">
              {'id' in draft ? 'Edit organization' : 'New organization'}
            </h2>
            <Field label="Name">
              <input
                className={input}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </Field>
            <Field label="Description">
              <textarea
                className={input}
                rows={3}
                value={draft.description ?? ''}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Email">
                <input
                  className={input}
                  value={draft.email ?? ''}
                  onChange={(e) => setDraft({ ...draft, email: e.target.value || null })}
                />
              </Field>
              <Field label="Website">
                <input
                  className={input}
                  value={draft.website ?? ''}
                  onChange={(e) => setDraft({ ...draft, website: e.target.value || null })}
                />
              </Field>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDraft(null)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={save}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
              >
                Save
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// View 2 — Locations for an organization
// ─────────────────────────────────────────────────────────────
function LocationsView({
  org, onSelect, onOrgRenamed,
}: {
  org: { id: string; name: string }
  onSelect: (l: { id: string; name: string }) => void
  onOrgRenamed: (name: string) => void
}) {
  const { data, err, reload } = useLoad(() => api.locations.listByOrg(org.id), [org.id])
  const [draft, setDraft] = useState<LocationIn | null>(null)
  const [geocoding, setGeocoding] = useState(false)
  const [geocodeErr, setGeocodeErr] = useState<string | null>(null)
  const [geocodeNote, setGeocodeNote] = useState<string | null>(null)

  void onOrgRenamed // reserved for rename

  const empty: LocationIn = {
    organization_id: org.id,
    name: '',
    alternate_name: null,
    description: null,
    address: null,
    latitude: null,
    longitude: null,
    extra: {},
  }

  async function save() {
    if (!draft) return
    try {
      // Build a clean LocationIn — do not echo id/created_at/updated_at back
      // (the backend uses extra="forbid" on LocationIn).
      const body: LocationIn = {
        organization_id: draft.organization_id ?? org.id,
        name: draft.name,
        alternate_name: draft.alternate_name,
        description: draft.description,
        address: draft.address,
        latitude: draft.latitude,
        longitude: draft.longitude,
        extra: draft.extra,
      }
      if ('id' in draft && typeof (draft as { id?: string }).id === 'string') {
        await api.locations.update((draft as Location).id, body)
      } else {
        await api.locations.create(body)
      }
      setDraft(null)
      setGeocodeErr(null)
      setGeocodeNote(null)
      reload()
    } catch (e) {
      alert((e as Error).message)
    }
  }

  async function geocodeAddress() {
    const address = draft?.address?.trim()
    if (!address) return
    setGeocoding(true)
    setGeocodeErr(null)
    setGeocodeNote(null)
    try {
      const hit = await api.geocode(address)
      if (!hit) {
        setGeocodeErr('No match found for this address.')
        return
      }
      setDraft((d) =>
        d
          ? { ...d, latitude: String(hit.lat), longitude: String(hit.lng) }
          : d,
      )
      setGeocodeNote(
        hit.display_name ? `Matched: ${hit.display_name}` : 'Coordinates resolved.',
      )
    } catch (e) {
      setGeocodeErr((e as Error).message)
    } finally {
      setGeocoding(false)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">
            Locations
            <span className="ml-2 text-xs font-normal text-slate-500">
              {data ? `(${data.length})` : ''}
            </span>
          </h2>
          <button
            onClick={() => {
              setDraft({ ...empty })
              setGeocodeErr(null)
              setGeocodeNote(null)
            }}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
          >
            New location
          </button>
        </div>
        <ErrorBanner message={err} />
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {(data ?? []).map((l) => (
            <li key={l.id} className="flex items-center">
              <button
                onClick={() => onSelect({ id: l.id, name: l.name ?? '(unnamed location)' })}
                className="flex-1 px-4 py-3 text-left hover:bg-slate-50"
              >
                <div className="font-medium text-slate-900">{l.name ?? '(unnamed location)'}</div>
                {l.address && (
                  <div className="line-clamp-1 text-xs text-slate-600">{l.address}</div>
                )}
                <div className="text-xs text-slate-500">
                  {l.latitude && l.longitude
                    ? `${l.latitude}, ${l.longitude}`
                    : 'not geocoded'}
                </div>
              </button>
              <button
                onClick={() => {
                  setDraft(l)
                  setGeocodeErr(null)
                  setGeocodeNote(null)
                }}
                className="px-3 py-3 text-xs text-slate-500 hover:text-slate-900"
              >
                Edit
              </button>
            </li>
          ))}
          {data && data.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-500">
              No locations for {org.name} yet.
            </li>
          )}
        </ul>
      </section>

      <section>
        {draft && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-medium">
              {'id' in draft ? 'Edit location' : 'New location'}
            </h2>

            <Field label="Name">
              <input
                className={input}
                value={draft.name ?? ''}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </Field>

            <Field label="Address">
              <div className="flex gap-2">
                <input
                  className={input}
                  placeholder="123 Main St, City, Country"
                  value={draft.address ?? ''}
                  onChange={(e) =>
                    setDraft({ ...draft, address: e.target.value || null })
                  }
                />
                <button
                  type="button"
                  onClick={geocodeAddress}
                  disabled={geocoding || !draft.address?.trim()}
                  className="whitespace-nowrap rounded-lg border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  {geocoding ? 'Looking up…' : 'Find coordinates'}
                </button>
              </div>
            </Field>
            {geocodeErr && (
              <p className="text-xs text-red-600">{geocodeErr}</p>
            )}
            {geocodeNote && !geocodeErr && (
              <p className="text-xs text-emerald-700">{geocodeNote}</p>
            )}

            <Field label="Coordinates (resolved from address)">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">
                {draft.latitude && draft.longitude
                  ? `${draft.latitude}, ${draft.longitude}`
                  : 'Not geocoded yet — enter an address and click “Find coordinates”.'}
              </div>
            </Field>

            <Field label="Description">
              <textarea
                className={input}
                rows={2}
                value={draft.description ?? ''}
                onChange={(e) => setDraft({ ...draft, description: e.target.value || null })}
              />
            </Field>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setDraft(null)
                  setGeocodeErr(null)
                  setGeocodeNote(null)
                }}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={save}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
              >
                Save
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// View 3 — Services for a location
// ─────────────────────────────────────────────────────────────
function LocationDetailView({
  org, loc, onBack, onLocRenamed,
}: {
  org: { id: string; name: string }
  loc: { id: string; name: string }
  onBack: () => void
  onLocRenamed: (name: string) => void
}) {
  const { data: location, err: locErr, reload: reloadLoc } = useLoad(
    () => api.locations.get(loc.id),
    [loc.id],
  )
  const { data: services, err: svcErr, reload: reloadSvc } = useLoad(
    () => api.locations.services.list(loc.id),
    [loc.id],
  )
  const [draft, setDraft] = useState<LocationServiceIn | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)

  void onLocRenamed // reserved for rename

  const empty: LocationServiceIn = {
    name: '',
    alternate_name: null,
    description: null,
    url: null,
    email: null,
    status: 'active',
    interpretation_services: null,
    application_process: null,
    fees_description: null,
    eligibility_description: null,
    minimum_age: null,
    maximum_age: null,
    assured_date: null,
    alert: null,
    last_modified: null,
    extra: {},
  }

  async function save() {
    if (!draft) return
    try {
      if (editingId) {
        // Update: reuse the top-level PATCH, supplying the org from the location.
        const body: ServiceIn = {
          ...draft,
          organization_id: location?.organization_id ?? org.id,
        }
        await api.services.update(editingId, body)
      } else {
        await api.locations.services.create(loc.id, draft)
      }
      setDraft(null)
      setEditingId(null)
      reloadSvc()
    } catch (e) {
      alert((e as Error).message)
    }
  }

  async function remove(s: LocationServiceOut) {
    if (!confirm(`Remove "${s.name}" from this location?`)) return
    try {
      await api.locations.services.remove(loc.id, s.id)
      reloadSvc()
    } catch (e) {
      alert((e as Error).message)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
      <section className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium">{location?.name ?? '(unnamed location)'}</h2>
            <button onClick={onBack} className="text-xs text-slate-500 hover:text-slate-900">
              ← {org.name}
            </button>
          </div>
          {location?.latitude && location?.longitude ? (
            <div className="mt-1 font-mono text-xs text-slate-500">
              {location.latitude}, {location.longitude}
            </div>
          ) : (
            <div className="mt-1 text-xs text-amber-700">No coordinates set</div>
          )}
          {location?.description && (
            <p className="mt-3 text-sm text-slate-600">{location.description}</p>
          )}
          <ErrorBanner message={locErr} />
          <button
            onClick={reloadLoc}
            className="mt-3 text-xs text-slate-500 hover:text-slate-900"
          >
            Refresh
          </button>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium uppercase tracking-wide text-slate-500">
              Services at this location
              {services && (
                <span className="ml-2 font-normal lowercase">({services.length})</span>
              )}
            </h3>
            <button
              onClick={() => { setEditingId(null); setDraft({ ...empty }) }}
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
            >
              New service
            </button>
          </div>
          <ErrorBanner message={svcErr} />
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
            {(services ?? []).map((s) => (
              <li key={s.id} className="flex items-center">
                <div className="flex-1 px-4 py-3">
                  <div className="font-medium text-slate-900">{s.name}</div>
                  {s.description && (
                    <div className="line-clamp-1 text-sm text-slate-600">{s.description}</div>
                  )}
                  <div className="text-xs text-slate-500">{s.status}</div>
                </div>
                <button
                  onClick={() => {
                    setEditingId(s.id)
                    setDraft({
                      name: s.name,
                      alternate_name: s.alternate_name,
                      description: s.description,
                      url: s.url,
                      email: s.email,
                      status: s.status,
                      interpretation_services: s.interpretation_services,
                      application_process: s.application_process,
                      fees_description: s.fees_description,
                      eligibility_description: s.eligibility_description,
                      minimum_age: s.minimum_age,
                      maximum_age: s.maximum_age,
                      assured_date: s.assured_date,
                      alert: s.alert,
                      last_modified: s.last_modified,
                      extra: s.extra,
                    })
                  }}
                  className="px-3 py-3 text-xs text-slate-500 hover:text-slate-900"
                >
                  Edit
                </button>
                <button
                  onClick={() => remove(s)}
                  className="px-3 py-3 text-xs text-red-600 hover:text-red-800"
                >
                  Remove
                </button>
              </li>
            ))}
            {services && services.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-slate-500">
                No services at this location yet.
              </li>
            )}
          </ul>
        </div>
      </section>

      <section>
        {draft && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-medium">
              {editingId ? 'Edit service' : 'New service'}
            </h2>
            <Field label="Name">
              <input
                className={input}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </Field>
            <Field label="Description">
              <textarea
                className={input}
                rows={3}
                value={draft.description ?? ''}
                onChange={(e) => setDraft({ ...draft, description: e.target.value || null })}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Status">
                <select
                  className={input}
                  value={draft.status}
                  onChange={(e) =>
                    setDraft({ ...draft, status: e.target.value as LocationServiceIn['status'] })
                  }
                >
                  {['active', 'inactive', 'defunct', 'temporarily closed'].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </Field>
              <Field label="Email">
                <input
                  className={input}
                  value={draft.email ?? ''}
                  onChange={(e) => setDraft({ ...draft, email: e.target.value || null })}
                />
              </Field>
            </div>
            <Field label="Eligibility">
              <textarea
                className={input}
                rows={2}
                value={draft.eligibility_description ?? ''}
                onChange={(e) =>
                  setDraft({ ...draft, eligibility_description: e.target.value || null })
                }
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => { setDraft(null); setEditingId(null) }}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={save}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
              >
                Save
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}