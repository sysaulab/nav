import { useEffect, useState } from 'react'
import { api, type LocationInput, type OrgOption } from '../api'
import { AddressAutocomplete } from './AddressAutocomplete'

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

export type LocationEditorInitial = {
  id?: string
  name: string | null
  alternate_name: string | null
  description: string | null
  address: string | null
  latitude: string | number | null
  longitude: string | number | null
  organization_id: string | null
}

export function LocationEditor({
  mode,
  initial,
  saving,
  onSave,
  onDelete,
}: {
  mode: 'create' | 'edit'
  initial: LocationEditorInitial | null
  saving: boolean
  onSave: (d: LocationInput) => void
  onDelete?: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [alternateName, setAlternateName] = useState(
    initial?.alternate_name ?? '',
  )
  const [description, setDescription] = useState(initial?.description ?? '')
  const [address, setAddress] = useState(initial?.address ?? '')
  const [lat, setLat] = useState(String(initial?.latitude ?? ''))
  const [lng, setLng] = useState(String(initial?.longitude ?? ''))
  const [orgId, setOrgId] = useState(initial?.organization_id ?? '')

  // When true, picking an address suggestion does not overwrite lat/lng.
  // Editing the address text by hand never touches lat/lng regardless —
  // the checkbox only governs suggestion-driven coordinate updates.
  const [freezeCoords, setFreezeCoords] = useState(
    !!(initial?.latitude && initial?.longitude),
  )

  const [orgs, setOrgs] = useState<OrgOption[]>([])

  useEffect(() => {
    let live = true
    api.directory.orgs
      .options()
      .then((opts) => {
        if (live) setOrgs(opts)
      })
      .catch(() => {
        /* silent — dropdown falls back to showing only the current org */
      })
    return () => {
      live = false
    }
  }, [])

  function handleAddressSelect(s: {
    display_name: string
    lat: number
    lng: number
  }) {
    setAddress(s.display_name)
    if (!freezeCoords) {
      setLat(String(s.lat))
      setLng(String(s.lng))
    }
  }

  const canSave = name.trim() !== '' && (mode === 'edit' || orgId !== '')

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!canSave) return
        onSave({
          organization_id: orgId || null,
          name: name.trim() || null,
          alternate_name: alternateName.trim() || null,
          description: description.trim() || null,
          address: address.trim() || null,
          latitude: lat.trim() === '' ? null : parseFloat(lat),
          longitude: lng.trim() === '' ? null : parseFloat(lng),
        })
      }}
      className="space-y-4"
    >
      <Field label="Organization">
        <select
          className={inputCls}
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          required={mode === 'create'}
        >
          <option value="">— select organization —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
          {orgId && !orgs.some((o) => o.id === orgId) && (
            <option value={orgId}>(current org)</option>
          )}
        </select>
      </Field>

      <Field label="Name">
        <input
          required
          className={inputCls}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Alternate Name">
        <input
          className={inputCls}
          value={alternateName}
          onChange={(e) => setAlternateName(e.target.value)}
        />
      </Field>
      <Field label="Description">
        <textarea
          className={inputCls}
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>

      <Field label="Address">
        <AddressAutocomplete
          value={address}
          onChange={setAddress}
          onSelect={handleAddressSelect}
          suggestionsEnabled={!freezeCoords}
          isFrozen={false}
          placeholder="123 Main St…"
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Latitude">
          <input
            type="number"
            step="any"
            className={inputCls}
            value={lat}
            onChange={(e) => setLat(e.target.value)}
          />
        </Field>
        <Field label="Longitude">
          <input
            type="number"
            step="any"
            className={inputCls}
            value={lng}
            onChange={(e) => setLng(e.target.value)}
          />
        </Field>
      </div>

      <label className="flex items-start gap-2 text-sm text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-200 cursor-pointer">
        <input
          type="checkbox"
          checked={freezeCoords}
          onChange={(e) => setFreezeCoords(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          <span className="font-medium">
            Picking an address does not move the pin
          </span>
          <span className="block text-xs text-slate-500 mt-0.5">
            Use this when Photon's coordinates are wrong. Uncheck to let an
            address selection overwrite lat/lng above.
          </span>
        </span>
      </label>

      <div className="flex justify-between pt-4">
        {onDelete ? (
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50"
          >
            Delete location
          </button>
        ) : (
          <span />
        )}
        <button
          type="submit"
          disabled={saving || !canSave}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}