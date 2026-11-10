// nav-admin/src/pages/Locations.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  ApiError,
  type GeocodeSuggestion,
  type LocationInput,
  type LocationSearchRow,
  type Service,
} from '../api'
import { LocationEditor } from '../components/LocationEditor'
import { DirectoryModals } from '../components/DirectoryModals'
import { AddressAutocomplete } from '../components/AddressAutocomplete'

const PAGE_SIZE = 25
const NAME_DEBOUNCE_MS = 333
const NAME_MIN_CHARS = 3

export default function Locations() {
  // ── Filter state ─────────────────────────────────────────
  const [nameQuery, setNameQuery] = useState('')
  const [originQuery, setOriginQuery] = useState('')
  const [origin, setOrigin] = useState<GeocodeSuggestion | null>(null)

  // Effective name filter — undefined below the minimum so the
  // backend sorts alphabetically with no name predicate.
  const effectiveQ =
    nameQuery.trim().length >= NAME_MIN_CHARS
      ? nameQuery.trim()
      : undefined

  // ── Results state ────────────────────────────────────────
  const [rows, setRows] = useState<LocationSearchRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Editor state ─────────────────────────────────────────
  const [selected, setSelected] = useState<LocationSearchRow | null>(null)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [services, setServices] = useState<Service[]>([])
  const [servicesLoading, setServicesLoading] = useState(false)
  const [svcModal, setSvcModal] = useState<
    { mode: 'create' | 'edit'; data?: Service } | null
  >(null)

  // ── Search ───────────────────────────────────────────────
  //
  // performSearch takes all inputs explicitly so it can be called from
  // the debounce effect (with the *current* effective filter) and from
  // pagination / save / delete (with the same filter). Empty useCallback
  // deps keep the identity stable, so the debounce effect only re-fires
  // when the effective filter actually changes.
  const performSearch = useCallback(
    async (args: {
      q?: string
      lat?: number
      lng?: number
      page: number
    }): Promise<LocationSearchRow[]> => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.directory.locations.search({
          q: args.q,
          lat: args.lat,
          lng: args.lng,
          page: args.page,
          page_size: PAGE_SIZE,
        })
        setRows(res.items)
        setTotal(res.total)
        setPage(res.page)
        return res.items
      } catch (e) {
        setError(e instanceof ApiError ? e.detail : (e as Error).message)
        setRows([])
        setTotal(0)
        return []
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  // Debounced search. Fire immediately on first mount (so the page
  // isn't blank for 333ms), then 333ms after each effective change.
  const firstRunRef = useRef(true)
  useEffect(() => {
    const delay = firstRunRef.current ? 0 : NAME_DEBOUNCE_MS
    firstRunRef.current = false
    const t = window.setTimeout(() => {
      void performSearch({
        q: effectiveQ,
        lat: origin?.lat,
        lng: origin?.lng,
        page: 1,
      })
    }, delay)
    return () => window.clearTimeout(t)
  }, [effectiveQ, origin?.lat, origin?.lng, performSearch])

  function goToPage(p: number) {
    void performSearch({
      q: effectiveQ,
      lat: origin?.lat,
      lng: origin?.lng,
      page: p,
    })
  }

  // ── Services for selected ────────────────────────────────
  const loadServices = useCallback(async (locId: string) => {
    setServicesLoading(true)
    try {
      const list = await api.directory.services.listForLoc(locId)
      setServices(list)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setServicesLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selected) void loadServices(selected.id)
    else setServices([])
  }, [selected, loadServices])

  // ── Save / delete location ───────────────────────────────
  async function saveLocation(d: LocationInput) {
    if (!creating && !selected) return
    setSaving(true)
    setSaveError(null)
    try {
      if (creating) {
        await api.directory.locations.createGlobal(d)
        setCreating(false)
        await performSearch({
          q: effectiveQ,
          lat: origin?.lat,
          lng: origin?.lng,
          page: 1,
        })
      } else if (selected) {
        await api.directory.locations.update(selected.id, d)
        const fresh = await performSearch({
          q: effectiveQ,
          lat: origin?.lat,
          lng: origin?.lng,
          page,
        })
        const updated = fresh.find((r) => r.id === selected.id)
        if (updated) setSelected(updated)
        await loadServices(selected.id)
      }
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function deleteLocation() {
    if (!selected) return
    if (
      !confirm(
        `Delete location "${selected.name || 'Untitled'}"?\n\n` +
          `This deletes every service at this location.`,
      )
    )
      return
    try {
      await api.directory.locations.remove(selected.id)
      setSelected(null)
      await performSearch({
        q: effectiveQ,
        lat: origin?.lat,
        lng: origin?.lng,
        page: 1,
      })
    } catch (e) {
      alert((e as Error).message)
    }
  }

  async function deleteService(s: Service) {
    if (!confirm(`Delete service "${s.name}"?`)) return
    try {
      await api.directory.services.remove(s.id)
      if (selected) {
        await loadServices(selected.id)
        await performSearch({
          q: effectiveQ,
          lat: origin?.lat,
          lng: origin?.lng,
          page,
        })
      }
    } catch (e) {
      alert((e as Error).message)
    }
  }

  // ── Render ───────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const nameCharsShort =
    nameQuery.length > 0 && nameQuery.trim().length < NAME_MIN_CHARS
  const originPending = originQuery.trim() !== '' && origin === null

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium text-slate-900">Locations</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {total.toLocaleString()} location{total === 1 ? '' : 's'}
            {origin
              ? ` · sorted by distance from ${origin.display_name}`
              : ' · sorted alphabetically'}
          </p>
        </div>
        <button
          onClick={() => {
            setCreating(true)
            setSelected(null)
          }}
          className="shrink-0 rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
        >
          New Location
        </button>
      </div>

      <div className="mb-4 space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">
            Filter by name
          </span>
          <input
            value={nameQuery}
            onChange={(e) => setNameQuery(e.target.value)}
            placeholder="Name or alternate name…"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          {nameCharsShort && (
            <span className="mt-1 block text-[11px] text-slate-500">
              Type {NAME_MIN_CHARS - nameQuery.trim().length} more
              character
              {NAME_MIN_CHARS - nameQuery.trim().length === 1 ? '' : 's'} to
              start filtering
            </span>
          )}
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">
            Sort by distance from
          </span>
          <AddressAutocomplete
            value={originQuery}
            onChange={(v) => {
              setOriginQuery(v)
              // Any edit to the text invalidates the previously picked
              // suggestion — the coordinates no longer correspond to the
              // visible address. The next search falls back to
              // alphabetical until a new suggestion is chosen.
              setOrigin(null)
            }}
            onSelect={(s) => {
              setOriginQuery(s.display_name)
              setOrigin(s)
            }}
            placeholder="Pick an address to sort by distance…"
            suggestionsEnabled
          />
          {originPending && (
            <span className="mt-1 block text-[11px] text-amber-700">
              Pick a suggestion from the dropdown to activate distance
              sorting.
            </span>
          )}
          {origin && (
            <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
              <span>
                Distance sort active from{' '}
                <span className="font-medium text-slate-700">
                  {origin.display_name}
                </span>
              </span>
              <button
                type="button"
                onClick={() => {
                  setOriginQuery('')
                  setOrigin(null)
                }}
                className="text-slate-400 underline hover:text-slate-700"
              >
                clear
              </button>
            </div>
          )}
        </label>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
        {/* Results list */}
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <ul className="max-h-[70vh] divide-y divide-slate-200 overflow-y-auto">
            {loading && rows.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-slate-500">
                Searching…
              </li>
            )}
            {!loading && rows.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-slate-500">
                No locations match.
              </li>
            )}
            {rows.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => {
                    setCreating(false)
                    setSelected(r)
                  }}
                  className={`block w-full px-4 py-3 text-left hover:bg-slate-50 ${
                    selected?.id === r.id ? 'bg-slate-100' : ''
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-medium text-slate-900">
                        {r.name || '(untitled)'}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">
                        {r.organization_name || '(no org)'} ·{' '}
                        {r.service_count} svc
                      </div>
                      {r.address && (
                        <div className="mt-0.5 truncate text-xs text-slate-500">
                          {r.address}
                        </div>
                      )}
                    </div>
                      {r.latitude === null ? (
                        <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 font-mono text-[11px] text-blue-700">
                          Global
                        </span>
                      ) : r.distance_km !== null ? (
                        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                          {r.distance_km.toFixed(1)} km
                        </span>
                      ) : null}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-200 px-4 py-2 text-xs">
              <span className="text-slate-500">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => goToPage(page - 1)}
                  disabled={page <= 1 || loading}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                >
                  ←
                </button>
                <button
                  onClick={() => goToPage(page + 1)}
                  disabled={page >= totalPages || loading}
                  className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
                >
                  →
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Editor pane */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          {creating && (
            <>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-900">
                  New location
                </h3>
                <button
                  onClick={() => setCreating(false)}
                  className="text-xs text-slate-500 hover:text-slate-900"
                >
                  Cancel
                </button>
              </div>
              {saveError && (
                <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
                  {saveError}
                </div>
              )}
              <LocationEditor
                key="new"
                mode="create"
                initial={null}
                saving={saving}
                onSave={saveLocation}
              />
            </>
          )}

          {!creating && !selected && (
            <div className="py-12 text-center text-sm text-slate-500">
              Select a location to edit, or create a new one.
            </div>
          )}

          {!creating && selected && (
            <>
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="truncate text-sm font-medium text-slate-900">
                  {selected.name || '(untitled)'}
                </h3>
                <span className="shrink-0 text-xs text-slate-500">
                  {selected.organization_name || '(no org)'}
                </span>
              </div>
              {saveError && (
                <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
                  {saveError}
                </div>
              )}
              <LocationEditor
                key={selected.id}
                mode="edit"
                initial={{
                  id: selected.id,
                  name: selected.name,
                  alternate_name: selected.alternate_name,
                  description: selected.description,
                  address: selected.address,
                  latitude: selected.latitude,
                  longitude: selected.longitude,
                  organization_id: selected.organization_id,
                }}
                saving={saving}
                onSave={saveLocation}
                onDelete={deleteLocation}
              />

              <div className="mt-6 border-t border-slate-200 pt-4">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-medium text-slate-900">
                    Services at this location
                  </h4>
                  <button
                    onClick={() => setSvcModal({ mode: 'create' })}
                    className="text-xs text-slate-700 hover:text-slate-900"
                  >
                    + Add service
                  </button>
                </div>
                {servicesLoading && (
                  <p className="py-2 text-xs text-slate-500">Loading…</p>
                )}
                {!servicesLoading && services.length === 0 && (
                  <p className="py-2 text-xs text-slate-500">
                    No services yet.
                  </p>
                )}
                <ul className="divide-y divide-slate-100">
                  {services.map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between py-2 text-sm"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-slate-900">
                          {s.name}
                        </div>
                        <div className="text-[11px] text-slate-500">
                          {s.status}
                          {s.description
                            ? ` · ${s.description.slice(0, 60)}${
                                s.description.length > 60 ? '…' : ''
                              }`
                            : ''}
                        </div>
                      </div>
                      <div className="ml-3 flex shrink-0 gap-2 text-xs">
                        <button
                          onClick={() =>
                            setSvcModal({ mode: 'edit', data: s })
                          }
                          className="text-slate-600 hover:text-slate-900"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => void deleteService(s)}
                          className="text-red-600 hover:text-red-800"
                        >
                          Delete
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>

      {svcModal && selected && (
        <DirectoryModals
          state={{
            type: 'svc',
            mode: svcModal.mode,
            locId: selected.id,
            data: svcModal.data,
          }}
          onClose={() => setSvcModal(null)}
          onSaved={async () => {
            setSvcModal(null)
            await loadServices(selected.id)
            const fresh = await performSearch({
              q: effectiveQ,
              lat: origin?.lat,
              lng: origin?.lng,
              page,
            })
            const updated = fresh.find((r) => r.id === selected.id)
            if (updated) setSelected(updated)
          }}
        />
      )}
    </div>
  )
}