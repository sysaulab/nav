import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, type PromptNearby, type PromptState } from '../api'

const inputCls =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none'

const monoCls =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-xs leading-relaxed focus:border-slate-500 focus:outline-none resize-y'

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block text-[11px] text-slate-500">{hint}</span>
      )}
    </label>
  )
}

function StatusBadge({ overridden }: { overridden: boolean }) {
  return overridden ? (
    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
      overridden
    </span>
  ) : (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
      default
    </span>
  )
}

export default function Prompt() {
  const [state, setState] = useState<PromptState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const s = await api.prompt.state()
      setState(s)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  if (loading && !state) {
    return (
      <div className="py-8 text-center text-sm text-slate-500">Loading…</div>
    )
  }
  if (!state) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        {error ?? 'Could not load prompt state.'}
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h2 className="text-lg font-medium text-slate-900">Prompt & Parameters</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Runtime-tunable behaviour. Changes take effect on the next chat turn.
          Reset restores the value baked into the deployment.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <PromptTextSection
        title="Chat personality"
        description="System prompt for the interview chat. This is where tone, conversation style, and the reveal loop live."
        currentText={state.chat_prompt}
        defaultText={state.defaults.chat_prompt}
        overridden={state.overridden.chat}
        onSave={async (text) => {
          await api.prompt.setChat(text)
          await reload()
        }}
        onReset={async () => {
          if (!confirm('Reset the chat prompt to the deployment default?'))
            return
          await api.prompt.reset('chat')
          await reload()
        }}
      />

      <PromptTextSection
        title="Finalize personality"
        description="System prompt used by the final plan-of-action endpoint. Kept separate so you can tighten the finalize output (citations, ordering) without touching chat tone."
        currentText={state.finalize_prompt}
        defaultText={state.defaults.finalize_prompt}
        overridden={state.overridden.finalize}
        onSave={async (text) => {
          await api.prompt.setFinalize(text)
          await reload()
        }}
        onReset={async () => {
          if (!confirm('Reset the finalize prompt to the deployment default?'))
            return
          await api.prompt.reset('finalize')
          await reload()
        }}
      />

      <NearbySection
        nearby={state.nearby}
        defaults={state.defaults.nearby}
        overridden={state.overridden.nearby}
        onSave={async (params) => {
          await api.prompt.setNearby(params)
          await reload()
        }}
        onReset={async () => {
          if (
            !confirm(
              'Reset nearby-search parameters to the deployment defaults?',
            )
          )
            return
          await api.prompt.reset('nearby')
          await reload()
        }}
      />
    </div>
  )
}

function PromptTextSection({
  title,
  description,
  currentText,
  defaultText,
  overridden,
  onSave,
  onReset,
}: {
  title: string
  description: string
  currentText: string
  defaultText: string
  overridden: boolean
  onSave: (text: string) => Promise<void>
  onReset: () => Promise<void>
}) {
  const [text, setText] = useState(currentText)
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setText(currentText)
  }, [currentText])

  const dirty = text !== currentText
  const defaultDiffers = defaultText !== currentText

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await onSave(text)
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 2000)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    setError(null)
    try {
      await onReset()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-slate-900">{title}</h3>
            <StatusBadge overridden={overridden} />
          </div>
          <p className="mt-0.5 text-xs text-slate-500">{description}</p>
        </div>
        <button
          onClick={() => void handleReset()}
          disabled={!overridden}
          className="shrink-0 rounded-lg border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          Reset to default
        </button>
      </header>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={18}
        spellCheck={false}
        className={monoCls}
      />

      {error && (
        <div className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {error}
        </div>
      )}

      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="text-[11px] text-slate-500">
          {text.length.toLocaleString()} chars
          {!overridden && defaultDiffers && (
            <span className="ml-2 text-amber-700">
              · resets to {defaultText.length.toLocaleString()} char default
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {justSaved && (
            <span className="text-xs text-emerald-600">Saved</span>
          )}
          <button
            onClick={() => void handleSave()}
            disabled={saving || !dirty || text.trim() === ''}
            className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </section>
  )
}

function NearbySection({
  nearby,
  defaults,
  overridden,
  onSave,
  onReset,
}: {
  nearby: PromptNearby
  defaults: PromptNearby
  overridden: boolean
  onSave: (p: PromptNearby) => Promise<void>
  onReset: () => Promise<void>
}) {
  const [radius, setRadius] = useState(String(nearby.radius_km))
  const [locLimit, setLocLimit] = useState(String(nearby.location_limit))
  const [idxLimit, setIdxLimit] = useState(String(nearby.index_limit))
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRadius(String(nearby.radius_km))
    setLocLimit(String(nearby.location_limit))
    setIdxLimit(String(nearby.index_limit))
  }, [nearby])

  const r = parseFloat(radius)
  const l = parseInt(locLimit, 10)
  const i = parseInt(idxLimit, 10)
  const numericOk =
    !Number.isNaN(r) &&
    !Number.isNaN(l) &&
    !Number.isNaN(i) &&
    r > 0 &&
    r <= 1000 &&
    l > 0 &&
    l <= 500 &&
    i > 0 &&
    i <= 2000
  const orderingOk = numericOk && l <= i
  const dirty =
    r !== nearby.radius_km ||
    l !== nearby.location_limit ||
    i !== nearby.index_limit

  async function handleSave() {
    if (!orderingOk) return
    setSaving(true)
    setError(null)
    try {
      await onSave({ radius_km: r, location_limit: l, index_limit: i })
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 2000)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-slate-900">
              Nearby-search parameters
            </h3>
            <StatusBadge overridden={overridden} />
          </div>
          <p className="mt-0.5 text-xs text-slate-500">
            How the 'Nearby services' list is built for each session. These
            govern the radius a service must be within, the number of
            locations drawn from it, and the total number of services exposed
            to the chat prompt.
          </p>
        </div>
        <button
          onClick={() => void onReset()}
          disabled={!overridden}
          className="shrink-0 rounded-lg border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          Reset to default
        </button>
      </header>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field
          label="Radius (km)"
          hint={`default ${defaults.radius_km}`}
        >
          <input
            type="number"
            step="0.1"
            min="0.1"
            max="1000"
            value={radius}
            onChange={(e) => setRadius(e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field
          label="Location limit"
          hint={`max ${defaults.location_limit} locations · default ${defaults.location_limit}`}
        >
          <input
            type="number"
            step="1"
            min="1"
            max="500"
            value={locLimit}
            onChange={(e) => setLocLimit(e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field
          label="Index limit"
          hint={`max ${defaults.index_limit} services · default ${defaults.index_limit}`}
        >
          <input
            type="number"
            step="1"
            min="1"
            max="2000"
            value={idxLimit}
            onChange={(e) => setIdxLimit(e.target.value)}
            className={inputCls}
          />
        </Field>
      </div>

      {!orderingOk && numericOk && (
        <p className="mt-2 text-xs text-red-700">
          Location limit must be ≤ index limit — the index is drawn from
          the locations, so it can't be smaller than the cap on them.
        </p>
      )}
      {!numericOk && (radius || locLimit || idxLimit) && (
        <p className="mt-2 text-xs text-red-700">
          Values out of range: radius 0.1–1000 km, location limit 1–500,
          index limit 1–2000.
        </p>
      )}

      {error && (
        <div className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {error}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="text-[11px] text-slate-500">
          {overridden
            ? 'Currently overridden in the database.'
            : 'Currently using deployment defaults.'}
        </div>
        <div className="flex items-center gap-2">
          {justSaved && (
            <span className="text-xs text-emerald-600">Saved</span>
          )}
          <button
            onClick={() => void handleSave()}
            disabled={saving || !dirty || !orderingOk}
            className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </section>
  )
}