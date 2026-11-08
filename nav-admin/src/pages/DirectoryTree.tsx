import { useCallback, useEffect, useState } from 'react'
import {
  api,
  ApiError,
  type LocationWithCount,
  type Organization,
  type Service,
} from '../api'
import { DirectoryModals } from '../components/DirectoryModals'
import { PhoneList } from '../components/PhoneList'

const PAGE_SIZE = 50

export default function DirectoryTree() {
  const [page, setPage] = useState(1)
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [expandedOrgs, setExpandedOrgs] = useState<Set<string>>(new Set())
  const [expandedLocs, setExpandedLocs] = useState<Set<string>>(new Set())

  const [locationsByOrg, setLocationsByOrg] = useState<Record<string, LocationWithCount[]>>({})
  const [servicesByLoc, setServicesByLoc] = useState<Record<string, Service[]>>({})

  const [modalState, setModalState] = useState<
    | { type: 'org'; mode: 'create' | 'edit'; data?: Organization }
    | { type: 'loc'; mode: 'create' | 'edit'; orgId: string; data?: LocationWithCount }
    | { type: 'svc'; mode: 'create' | 'edit'; locId: string; data?: Service }
    | null
  >(null)

  // ── data loading ─────────────────────────────────────

  const loadOrgs = useCallback(async (p: number) => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.directory.orgs.list(p, PAGE_SIZE)
      setOrgs(result.items)
      setTotal(result.total)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadOrgs(page)
  }, [page, loadOrgs])

  const refreshLocsForOrg = useCallback(async (orgId: string) => {
    try {
      const locs = await api.directory.locations.listForOrg(orgId)
      setLocationsByOrg((m) => ({ ...m, [orgId]: locs }))
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }, [])

  const refreshSvcsForLoc = useCallback(async (locId: string) => {
    try {
      const svcs = await api.directory.services.listForLoc(locId)
      setServicesByLoc((m) => ({ ...m, [locId]: svcs }))
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }, [])

  // ── expansion ────────────────────────────────────────

  async function toggleOrg(orgId: string) {
    const next = new Set(expandedOrgs)
    if (next.has(orgId)) {
      next.delete(orgId)
      setExpandedOrgs(next)
      return
    }
    next.add(orgId)
    setExpandedOrgs(next)
    if (!locationsByOrg[orgId]) await refreshLocsForOrg(orgId)
  }

  async function toggleLoc(locId: string) {
    const next = new Set(expandedLocs)
    if (next.has(locId)) {
      next.delete(locId)
      setExpandedLocs(next)
      return
    }
    next.add(locId)
    setExpandedLocs(next)
    if (!servicesByLoc[locId]) await refreshSvcsForLoc(locId)
  }

  // ── delete handlers ──────────────────────────────────

  async function handleDeleteOrg(org: Organization) {
    if (
      !confirm(
        `Delete "${org.name}"?\n\nThis will permanently delete all locations and services under this organization.`,
      )
    )
      return
    try {
      await api.directory.orgs.remove(org.id)
      setExpandedOrgs((s) => {
        const n = new Set(s)
        n.delete(org.id)
        return n
      })
      setLocationsByOrg((m) => {
        const n = { ...m }
        delete n[org.id]
        return n
      })
      await loadOrgs(page)
    } catch (e) {
      alert((e as Error).message)
    }
  }

  async function handleDeleteLoc(loc: LocationWithCount, orgId: string) {
    if (
      !confirm(
        `Delete location "${loc.name || 'Untitled'}"?\n\nThis will permanently delete all services at this location.`,
      )
    )
      return
    try {
      await api.directory.locations.remove(loc.id)
      setExpandedLocs((s) => {
        const n = new Set(s)
        n.delete(loc.id)
        return n
      })
      setServicesByLoc((m) => {
        const n = { ...m }
        delete n[loc.id]
        return n
      })
      await refreshLocsForOrg(orgId)
    } catch (e) {
      alert((e as Error).message)
    }
  }

  async function handleDeleteSvc(svc: Service, locId: string) {
    if (!confirm(`Delete service "${svc.name}"?`)) return
    try {
      await api.directory.services.remove(svc.id)
      await refreshSvcsForLoc(locId)
    } catch (e) {
      alert((e as Error).message)
    }
  }

  // ── render ───────────────────────────────────────────

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-medium text-slate-900">Directory</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {total.toLocaleString()} organizations
          </p>
        </div>
        <button
          onClick={() => setModalState({ type: 'org', mode: 'create' })}
          className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
        >
          New Organization
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {loading && orgs.length === 0 && (
          <div className="py-8 text-center text-sm text-slate-500">Loading…</div>
        )}
        {!loading && orgs.length === 0 && (
          <div className="py-8 text-center text-sm text-slate-500">
            No organizations yet.
          </div>
        )}

        {orgs.map((org) => {
          const isOrgExp = expandedOrgs.has(org.id)
          const locs = locationsByOrg[org.id]

          return (
            <div
              key={org.id}
              className="rounded-xl border-2 border-slate-900 bg-slate-900 text-white overflow-hidden"
            >
              <div className="flex items-start justify-between gap-3 p-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <button
                    onClick={() => void toggleOrg(org.id)}
                    className="text-slate-400 hover:text-white font-mono text-lg w-6 shrink-0 mt-0.5"
                  >
                    {isOrgExp ? '−' : '+'}
                  </button>
                  <div className="min-w-0">
                    <h3 className="font-semibold">{org.name || '(unnamed)'}</h3>
                    {org.description && (
                      <p className="text-xs text-slate-400 line-clamp-1">
                        {org.description}
                      </p>
                    )}
                    <PhoneList
                      ownerType="org"
                      ownerId={org.id}
                      phones={org.phones || []}
                      onRefresh={() => void loadOrgs(page)}
                      theme="dark"
                    />
                  </div>
                </div>
                <div className="flex gap-2 text-xs shrink-0">
                  <button
                    onClick={() =>
                      setModalState({ type: 'org', mode: 'edit', data: org })
                    }
                    className="text-slate-300 hover:text-white"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => void handleDeleteOrg(org)}
                    className="text-red-400 hover:text-red-300"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {isOrgExp && (
                <div className="border-t border-slate-700/50 bg-slate-800 p-3 pl-10 space-y-2">
                  {!locs && (
                    <p className="text-xs text-slate-400 py-2">Loading locations…</p>
                  )}
                  {locs && locs.length === 0 && (
                    <p className="text-xs text-slate-400 py-2">No locations yet.</p>
                  )}

                  {locs?.map((loc) => {
                    const isLocExp = expandedLocs.has(loc.id)
                    const svcs = servicesByLoc[loc.id]

                    return (
                      <div
                        key={loc.id}
                        className="rounded-lg border border-slate-700 bg-slate-800 overflow-hidden"
                      >
                        <div className="flex items-start justify-between gap-3 p-3">
                          <div className="flex items-start gap-3 flex-1 min-w-0">
                            <button
                              onClick={() => void toggleLoc(loc.id)}
                              className="text-slate-400 hover:text-white font-mono text-base w-5 shrink-0 mt-0.5"
                            >
                              {isLocExp ? '−' : '+'}
                            </button>
                            <div className="min-w-0">
                              <h4 className="text-sm font-medium">
                                {loc.name || '(untitled location)'}
                              </h4>
                              {loc.address && (
                                <p className="text-xs text-slate-400 line-clamp-1">
                                  {loc.address}
                                </p>
                              )}
                              <PhoneList
                                ownerType="loc"
                                ownerId={loc.id}
                                phones={loc.phones || []}
                                onRefresh={() => void refreshLocsForOrg(org.id)}
                                theme="dark"
                              />
                            </div>
                          </div>
                          <div className="flex items-center gap-3 text-xs shrink-0">
                            <span className="text-slate-400 bg-slate-900/50 px-2 py-0.5 rounded">
                              {loc.service_count} svc
                            </span>
                            <button
                              onClick={() =>
                                setModalState({
                                  type: 'loc',
                                  mode: 'edit',
                                  orgId: org.id,
                                  data: loc,
                                })
                              }
                              className="text-slate-300 hover:text-white"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => void handleDeleteLoc(loc, org.id)}
                              className="text-red-400 hover:text-red-300"
                            >
                              Delete
                            </button>
                          </div>
                        </div>

                        {isLocExp && (
                          <div className="border-t border-slate-700/50 bg-slate-700 p-2 pl-8 space-y-1">
                            {!svcs && (
                              <p className="text-xs text-slate-300 py-1">
                                Loading services…
                              </p>
                            )}
                            {svcs && svcs.length === 0 && (
                              <p className="text-xs text-slate-300 py-1">
                                No services yet.
                              </p>
                            )}

                            {svcs?.map((svc) => (
                              <div
                                key={svc.id}
                                className="flex flex-col py-1.5 px-2 hover:bg-slate-600/50 rounded group"
                              >
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-3 min-w-0">
                                    <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0" />
                                    <span className="text-sm text-slate-200 truncate">
                                      {svc.name}
                                    </span>
                                    {svc.status !== 'active' && (
                                      <span className="text-[10px] uppercase tracking-wider text-amber-400 border border-amber-400/30 px-1.5 rounded shrink-0">
                                        {svc.status}
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex gap-2 text-xs opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-3">
                                    <button
                                      onClick={() =>
                                        setModalState({
                                          type: 'svc',
                                          mode: 'edit',
                                          locId: loc.id,
                                          data: svc,
                                        })
                                      }
                                      className="text-slate-300 hover:text-white"
                                    >
                                      Edit
                                    </button>
                                    <button
                                      onClick={() => void handleDeleteSvc(svc, loc.id)}
                                      className="text-red-400 hover:text-red-300"
                                    >
                                      Remove
                                    </button>
                                  </div>
                                </div>
                                <div className="pl-[18px]">
                                  <PhoneList
                                    ownerType="svc"
                                    ownerId={svc.id}
                                    phones={svc.phones || []}
                                    onRefresh={() => void refreshSvcsForLoc(loc.id)}
                                    theme="dark"
                                  />
                                </div>
                              </div>
                            ))}

                            <div className="pt-2">
                              <button
                                onClick={() =>
                                  setModalState({
                                    type: 'svc',
                                    mode: 'create',
                                    locId: loc.id,
                                  })
                                }
                                className="text-xs text-slate-300 hover:text-white flex items-center gap-1"
                              >
                                <span>+</span> Add service
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}

                  <div className="pt-1">
                    <button
                      onClick={() =>
                        setModalState({
                          type: 'loc',
                          mode: 'create',
                          orgId: org.id,
                        })
                      }
                      className="text-xs text-slate-300 hover:text-white flex items-center gap-1"
                    >
                      <span>+</span> Add location
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex items-center justify-between text-sm">
        <span className="text-slate-500">
          Page {page} of {totalPages}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            ← Prev
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Next →
          </button>
        </div>
      </div>

      {modalState && (
        <DirectoryModals
          state={modalState}
          onClose={() => setModalState(null)}
          onSaved={async () => {
            const closed = modalState
            setModalState(null)
            if (closed.type === 'org') {
              await loadOrgs(page)
            } else if (closed.type === 'loc') {
              await refreshLocsForOrg(closed.orgId)
            } else if (closed.type === 'svc') {
              await refreshSvcsForLoc(closed.locId)
              // Service count on the parent location may have changed
              const orgId = Object.keys(locationsByOrg).find((k) =>
                locationsByOrg[k].some((l) => l.id === closed.locId),
              )
              if (orgId) await refreshLocsForOrg(orgId)
            }
          }}
        />
      )}
    </div>
  )
}