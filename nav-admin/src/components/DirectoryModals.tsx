import { useState } from 'react'
import {
  api,
  ApiError,
  type Organization,
  type OrganizationInput,
  type LocationWithCount,
  type LocationInput,
  type Service,
  type ServiceInput,
} from '../api'
import { LocationEditor } from './LocationEditor'

const inputCls =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none'

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  )
}

function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`
}

export function DirectoryModals({
  state,
  onClose,
  onSaved,
}: {
  state:
    | { type: 'org'; mode: 'create' | 'edit'; data?: Organization }
    | {
        type: 'loc'
        mode: 'create' | 'edit'
        orgId: string
        data?: LocationWithCount
      }
    | { type: 'svc'; mode: 'create' | 'edit'; locId: string; data?: Service }
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave(payload: any) {
    setSaving(true)
    setError(null)
    try {
      if (state.type === 'org') {
        if (state.mode === 'create')
          await api.directory.orgs.create(payload as OrganizationInput)
        else
          await api.directory.orgs.update(
            state.data!.id,
            payload as OrganizationInput,
          )
      } else if (state.type === 'loc') {
        const locInput = payload as LocationInput
        if (!locInput.organization_id) {
          throw new ApiError(400, 'Select an organization')
        }
        if (state.mode === 'create') {
          await api.directory.locations.createGlobal(locInput)
        } else {
          await api.directory.locations.update(state.data!.id, locInput)
        }
      } else if (state.type === 'svc') {
        if (state.mode === 'create')
          await api.directory.services.create(
            state.locId,
            payload as ServiceInput,
          )
        else
          await api.directory.services.update(
            state.data!.id,
            payload as ServiceInput,
          )
      }
      await onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
      setSaving(false)
    }
  }

  async function handleDeleteLoc(id: string) {
    if (!confirm('Delete this location and every service at it?')) return
    setSaving(true)
    setError(null)
    try {
      await api.directory.locations.remove(id)
      await onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-xl flex flex-col">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-lg font-semibold text-slate-900">
            {state.mode === 'create' ? 'New' : 'Edit'}{' '}
            {state.type === 'org'
              ? 'Organization'
              : state.type === 'loc'
              ? 'Location'
              : 'Service'}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-900 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="p-6">
          {error && (
            <div className="mb-4 rounded-lg bg-red-50 text-red-800 p-3 text-sm border border-red-200">
              {error}
            </div>
          )}

          {state.type === 'org' && (
            <OrgForm
              initial={state.data}
              onSave={handleSave}
              saving={saving}
            />
          )}
          {state.type === 'loc' && (
            <LocationEditor
              mode={state.mode}
              initial={
                state.data
                  ? {
                      id: state.data.id,
                      name: state.data.name,
                      alternate_name: state.data.alternate_name ?? null,
                      description: state.data.description ?? null,
                      address: state.data.address,
                      latitude: state.data.latitude,
                      longitude: state.data.longitude,
                      organization_id: state.orgId,
                    }
                  : {
                      name: null,
                      alternate_name: null,
                      description: null,
                      address: null,
                      latitude: null,
                      longitude: null,
                      organization_id: state.orgId,
                    }
              }
              saving={saving}
              onSave={(d) => void handleSave(d)}
              onDelete={
                state.mode === 'edit' && state.data
                  ? () => void handleDeleteLoc(state.data!.id)
                  : undefined
              }
            />
          )}
          {state.type === 'svc' && (
            <SvcForm
              initial={state.data}
              onSave={handleSave}
              saving={saving}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Org Form ─────────────────────────────────────────────

function OrgForm({
  initial,
  onSave,
  saving,
}: {
  initial?: Organization
  onSave: (d: OrganizationInput) => void
  saving: boolean
}) {
  const [d, setD] = useState<OrganizationInput>({
    name: initial?.name ?? '',
    alternate_name: initial?.alternate_name ?? null,
    description: initial?.description ?? '',
    email: initial?.email ?? null,
    website: initial?.website ?? null,
    legal_status: initial?.legal_status ?? null,
    year_incorporated: initial?.year_incorporated ?? null,
    logo: initial?.logo ?? null,
    uri: initial?.uri ?? null,
    parent_organization_id: initial?.parent_organization_id ?? null,
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSave(d)
      }}
      className="space-y-4"
    >
      <Field label="Name">
        <input
          required
          className={inputCls}
          value={d.name}
          onChange={(e) => setD({ ...d, name: e.target.value })}
        />
      </Field>
      <Field label="Alternate Name">
        <input
          className={inputCls}
          value={d.alternate_name ?? ''}
          onChange={(e) =>
            setD({ ...d, alternate_name: e.target.value || null })
          }
        />
      </Field>
      <Field label="Description">
        <textarea
          className={inputCls}
          rows={3}
          value={d.description}
          onChange={(e) => setD({ ...d, description: e.target.value })}
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Email">
          <input
            type="email"
            className={inputCls}
            value={d.email ?? ''}
            onChange={(e) => setD({ ...d, email: e.target.value || null })}
          />
        </Field>
        <Field label="Website">
          <input
            type="url"
            className={inputCls}
            value={d.website ?? ''}
            onChange={(e) => setD({ ...d, website: e.target.value || null })}
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Legal Status">
          <input
            className={inputCls}
            value={d.legal_status ?? ''}
            onChange={(e) =>
              setD({ ...d, legal_status: e.target.value || null })
            }
          />
        </Field>
        <Field label="Year Incorporated">
          <input
            type="number"
            className={inputCls}
            value={d.year_incorporated ?? ''}
            onChange={(e) =>
              setD({
                ...d,
                year_incorporated: parseInt(e.target.value) || null,
              })
            }
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Logo URL">
          <input
            type="url"
            className={inputCls}
            value={d.logo ?? ''}
            onChange={(e) => setD({ ...d, logo: e.target.value || null })}
          />
        </Field>
        <Field label="URI">
          <input
            type="url"
            className={inputCls}
            value={d.uri ?? ''}
            onChange={(e) => setD({ ...d, uri: e.target.value || null })}
          />
        </Field>
      </div>

      <div className="flex justify-end pt-4">
        <button
          type="submit"
          disabled={saving || !d.name.trim()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

// ── Svc Form ─────────────────────────────────────────────

function SvcForm({
  initial,
  onSave,
  saving,
}: {
  initial?: Service
  onSave: (d: ServiceInput) => void
  saving: boolean
}) {
  const [d, setD] = useState<ServiceInput>({
    name: initial?.name ?? '',
    alternate_name: initial?.alternate_name ?? null,
    description: initial?.description ?? null,
    url: initial?.url ?? null,
    email: initial?.email ?? null,
    status: (initial?.status as any) ?? 'active',
    interpretation_services: initial?.interpretation_services ?? null,
    application_process: initial?.application_process ?? null,
    fees_description: initial?.fees_description ?? null,
    eligibility_description: initial?.eligibility_description ?? null,
    minimum_age: initial?.minimum_age ?? null,
    maximum_age: initial?.maximum_age ?? null,
    assured_date: initial?.assured_date ?? null,
    alert: initial?.alert ?? null,
    last_modified: initial?.last_modified ?? null,
  })

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSave(d)
      }}
      className="space-y-4"
    >
      <Field label="Name">
        <input
          required
          className={inputCls}
          value={d.name}
          onChange={(e) => setD({ ...d, name: e.target.value })}
        />
      </Field>
      <Field label="Alternate Name">
        <input
          className={inputCls}
          value={d.alternate_name ?? ''}
          onChange={(e) =>
            setD({ ...d, alternate_name: e.target.value || null })
          }
        />
      </Field>
      <Field label="Description">
        <textarea
          className={inputCls}
          rows={3}
          value={d.description ?? ''}
          onChange={(e) =>
            setD({ ...d, description: e.target.value || null })
          }
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Status">
          <select
            className={inputCls}
            value={d.status}
            onChange={(e) =>
              setD({ ...d, status: e.target.value as any })
            }
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="temporarily closed">Temporarily Closed</option>
            <option value="defunct">Defunct</option>
          </select>
        </Field>
        <Field label="Email">
          <input
            type="email"
            className={inputCls}
            value={d.email ?? ''}
            onChange={(e) => setD({ ...d, email: e.target.value || null })}
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="URL">
          <input
            type="url"
            className={inputCls}
            value={d.url ?? ''}
            onChange={(e) => setD({ ...d, url: e.target.value || null })}
          />
        </Field>
        <Field label="Interpretation Services">
          <input
            className={inputCls}
            value={d.interpretation_services ?? ''}
            onChange={(e) =>
              setD({
                ...d,
                interpretation_services: e.target.value || null,
              })
            }
          />
        </Field>
      </div>

      <Field label="Eligibility">
        <textarea
          className={inputCls}
          rows={2}
          value={d.eligibility_description ?? ''}
          onChange={(e) =>
            setD({ ...d, eligibility_description: e.target.value || null })
          }
        />
      </Field>
      <Field label="How to apply">
        <textarea
          className={inputCls}
          rows={2}
          value={d.application_process ?? ''}
          onChange={(e) =>
            setD({ ...d, application_process: e.target.value || null })
          }
        />
      </Field>
      <Field label="Fees">
        <textarea
          className={inputCls}
          rows={2}
          value={d.fees_description ?? ''}
          onChange={(e) =>
            setD({ ...d, fees_description: e.target.value || null })
          }
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Minimum Age">
          <input
            type="number"
            className={inputCls}
            value={d.minimum_age ?? ''}
            onChange={(e) =>
              setD({
                ...d,
                minimum_age: parseFloat(e.target.value) || null,
              })
            }
          />
        </Field>
        <Field label="Maximum Age">
          <input
            type="number"
            className={inputCls}
            value={d.maximum_age ?? ''}
            onChange={(e) =>
              setD({
                ...d,
                maximum_age: parseFloat(e.target.value) || null,
              })
            }
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Assured Date">
          <input
            type="datetime-local"
            className={inputCls}
            value={toDatetimeLocal(d.assured_date)}
            onChange={(e) =>
              setD({ ...d, assured_date: e.target.value || null })
            }
          />
        </Field>
        <Field label="Last Modified">
          <input
            type="datetime-local"
            className={inputCls}
            value={toDatetimeLocal(d.last_modified)}
            onChange={(e) =>
              setD({ ...d, last_modified: e.target.value || null })
            }
          />
        </Field>
      </div>

      <Field label="Alert">
        <textarea
          className={inputCls}
          rows={2}
          value={d.alert ?? ''}
          onChange={(e) => setD({ ...d, alert: e.target.value || null })}
        />
      </Field>

      <div className="flex justify-end pt-4">
        <button
          type="submit"
          disabled={saving || !d.name.trim()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}