import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, type Defaults, type ModelSpec } from '../api'

const EMPTY: ModelSpec = {
  id: '',
  module: 'ollama',
  endpoint: 'http://127.0.0.1:11434',
  model: '',
  context_window: 8192,
  max_output_tokens: 2048,
  label: '',
  api_key_env: null,
  enabled: true,
}

const input =
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
      {label && (
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
          {label}
        </span>
      )}
      {children}
    </label>
  )
}

export default function Models() {
  const [models, setModels] = useState<ModelSpec[]>([])
  const [defaults, setDefaults] = useState<Defaults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<ModelSpec | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    try {
      const [list, d] = await Promise.all([
        api.models.list(),
        api.models.defaults(),
      ])
      setModels(list)
      setDefaults(d)
      setError(null)
    } catch (e) {
      setError(
        e instanceof ApiError ? e.detail : (e as Error).message,
      )
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function save() {
    if (!editing) return
    setSaving(true)
    setError(null)
    try {
      await api.models.put(editing.id, editing)
      setEditing(null)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    if (!confirm(`Delete model override for ${id}?`)) return
    try {
      await api.models.remove(id)
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  async function setDefault(which: 'chat' | 'finalize', id: string) {
    try {
      await api.models.setDefaults({ [which]: id })
      await reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium text-slate-900">Models</h2>
          <button
            onClick={() => setEditing({ ...EMPTY })}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
          >
            New model
          </button>
        </div>
        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {models.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-500">
              No models configured.
            </li>
          )}
          {models.map((m) => {
            const isChat = defaults?.chat === m.id
            const isFinal = defaults?.finalize === m.id
            return (
              <li key={m.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-slate-900">
                        {m.label || m.id}
                      </span>
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-500">
                        {m.module}
                      </span>
                      {!m.enabled && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">
                          disabled
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-500">
                      {m.id} · {m.model} ·{' '}
                      {(m.context_window / 1000).toFixed(0)}k /{' '}
                      {(m.max_output_tokens / 1000).toFixed(1)}k out
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <button
                        onClick={() => void setDefault('chat', m.id)}
                        disabled={isChat}
                        className={`rounded border px-2 py-0.5 ${
                          isChat
                            ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                            : 'border-slate-300 text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        {isChat ? 'chat default' : 'set chat'}
                      </button>
                      <button
                        onClick={() => void setDefault('finalize', m.id)}
                        disabled={isFinal}
                        className={`rounded border px-2 py-0.5 ${
                          isFinal
                            ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                            : 'border-slate-300 text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        {isFinal ? 'finalize default' : 'set finalize'}
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <button
                      onClick={() => setEditing({ ...m })}
                      className="text-xs text-slate-500 hover:text-slate-900"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => void remove(m.id)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      <section>
        {editing && (
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-medium">
              {editing.model ? `Edit ${editing.id}` : 'New model'}
            </h2>
            <Field label="ID">
              <input
                className={input}
                value={editing.id}
                onChange={(e) =>
                  setEditing({ ...editing, id: e.target.value })
                }
                disabled={!!editing.model}
                placeholder="ollama-gemma4-cloud"
              />
            </Field>
            <Field label="Label">
              <input
                className={input}
                value={editing.label}
                onChange={(e) =>
                  setEditing({ ...editing, label: e.target.value })
                }
                placeholder="Gemma 4 (Ollama Cloud)"
              />
            </Field>
            <Field label="Module">
              <select
                className={input}
                value={editing.module}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    module: e.target.value as 'ollama' | 'openai',
                  })
                }
              >
                <option value="ollama">ollama</option>
                <option value="openai">openai</option>
              </select>
            </Field>
            <Field label="Endpoint">
              <input
                className={input}
                value={editing.endpoint}
                onChange={(e) =>
                  setEditing({ ...editing, endpoint: e.target.value })
                }
                placeholder="http://host.docker.internal:11434"
              />
            </Field>
            <Field label="Model name">
              <input
                className={input}
                value={editing.model}
                onChange={(e) =>
                  setEditing({ ...editing, model: e.target.value })
                }
                placeholder="gemma4:cloud"
              />
            </Field>
            {editing.module === 'openai' && (
              <Field label="API key env var">
                <input
                  className={input}
                  value={editing.api_key_env ?? ''}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      api_key_env: e.target.value || null,
                    })
                  }
                  placeholder="OPENAI_API_KEY"
                />
              </Field>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Context window">
                <input
                  className={input}
                  type="number"
                  value={editing.context_window}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      context_window: parseInt(e.target.value, 10) || 0,
                    })
                  }
                />
              </Field>
              <Field label="Max output">
                <input
                  className={input}
                  type="number"
                  value={editing.max_output_tokens}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      max_output_tokens: parseInt(e.target.value, 10) || 0,
                    })
                  }
                />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={editing.enabled}
                onChange={(e) =>
                  setEditing({ ...editing, enabled: e.target.checked })
                }
              />
              Enabled
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setEditing(null)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={() => void save()}
                disabled={saving || !editing.id || !editing.model}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}