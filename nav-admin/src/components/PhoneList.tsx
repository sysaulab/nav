import { useState } from 'react'
import { api, type Phone, type PhoneInput } from '../api'

// Added text-slate-900 and placeholder-slate-400 to ensure inputs are visible
const inputCls = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-slate-500 focus:outline-none'

export function PhoneList({
  ownerType,
  ownerId,
  phones,
  onRefresh,
  theme = 'dark',
}: {
  ownerType: 'org' | 'loc' | 'svc'
  ownerId: string
  phones: Phone[]
  onRefresh: () => void
  theme?: 'dark' | 'light'
}) {
  const [editing, setEditing] = useState<Phone | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  const textBase = theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
  const textHover = theme === 'dark' ? 'hover:text-white' : 'hover:text-slate-900'

  function startCreate() {
    setEditing(null)
    setIsCreating(true)
  }

  function startEdit(p: Phone) {
    setEditing(p)
    setIsCreating(false)
  }

  async function handleDelete(p: Phone) {
    if (!confirm(`Delete phone ${p.number}?`)) return
    try {
      await api.directory.phones.remove(p.id)
      onRefresh()
    } catch (e) {
      alert((e as Error).message)
    }
  }

  return (
    <div className="mt-1">
      <div className="flex flex-col gap-0.5">
        {phones.map((p) => (
          <div key={p.id} className="group flex items-center gap-2 text-xs">
            <span className={`${textBase}`}>☎</span>
            <span className={`${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>
              {p.number}
              {p.type ? ` (${p.type})` : ''}
            </span>
            <div className="opacity-0 group-hover:opacity-100 flex gap-1 ml-1">
              <button onClick={() => startEdit(p)} className={`${textBase} ${textHover}`}>edit</button>
              <button onClick={() => void handleDelete(p)} className="text-red-400 hover:text-red-300">del</button>
            </div>
          </div>
        ))}
      </div>
      <button
        onClick={startCreate}
        className={`mt-1 text-xs flex items-center gap-1 opacity-50 hover:opacity-100 ${textBase} ${textHover} transition-opacity`}
      >
        <span>+</span> Add phone
      </button>

      {(isCreating || editing) && (
        <PhoneFormModal
          initial={editing ?? undefined}
          ownerType={ownerType}
          ownerId={ownerId}
          onClose={() => { setIsCreating(false); setEditing(null) }}
          onSaved={() => { setIsCreating(false); setEditing(null); onRefresh() }}
        />
      )}
    </div>
  )
}

function PhoneFormModal({ initial, ownerType, ownerId, onClose, onSaved }: {
  initial?: Phone
  ownerType: 'org' | 'loc' | 'svc'
  ownerId: string
  onClose: () => void
  onSaved: () => void
}) {
  const [d, setD] = useState<PhoneInput>({
    number: initial?.number ?? '',
    type: initial?.type ?? null,
    extension: initial?.extension ?? null,
    language: initial?.language ?? null,
    description: initial?.description ?? null,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (initial) {
        await api.directory.phones.update(initial.id, d)
      } else {
        await api.directory.phones.create(ownerType, ownerId, d)
      }
      onSaved()
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      {/* Added text-slate-900 to the form to override inherited white text */}
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white shadow-xl flex flex-col text-slate-900">
        <div className="border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{initial ? 'Edit Phone' : 'Add Phone'}</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-900 text-xl leading-none">&times;</button>
        </div>
        
        <div className="p-6 space-y-4">
          {error && <div className="rounded-lg bg-red-50 text-red-800 p-2 text-xs border border-red-200">{error}</div>}
          
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Number</span>
            <input required autoFocus className={inputCls} value={d.number} onChange={e => setD({...d, number: e.target.value})} placeholder="(604) 555-1234" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Type</span>
              <select className={inputCls} value={d.type ?? ''} onChange={e => setD({...d, type: e.target.value || null})}>
                <option value="">—</option>
                <option value="voice">Voice</option>
                <option value="text">Text</option>
                <option value="fax">Fax</option>
                <option value="tty">TTY</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Extension</span>
              <input className={inputCls} value={d.extension ?? ''} onChange={e => setD({...d, extension: e.target.value || null})} />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Language</span>
            <input className={inputCls} value={d.language ?? ''} onChange={e => setD({...d, language: e.target.value || null})} placeholder="English, French…" />
          </label>
        </div>
        
        <div className="border-t border-slate-200 px-6 py-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Cancel</button>
          <button type="submit" disabled={saving || !d.number.trim()} className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </div>
  )
}