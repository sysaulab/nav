import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, ApiError,
  type LanguageCoverage, type TranslationJob, type UiStringRow,
} from '../api'
import { LANGUAGES, PROMOTED_LOCALES, languageNative, languageName } from '../languages'

const DEFAULT_LOCALE = 'fr'
const LOCALSTORAGE_KEY = 'nav_admin_language'

export default function Languages() {
  const [locale, setLocaleState] = useState<string>(() => {
    return localStorage.getItem(LOCALSTORAGE_KEY) || DEFAULT_LOCALE
  })

  const setLocale = (l: string) => {
    localStorage.setItem(LOCALSTORAGE_KEY, l)
    setLocaleState(l)
  }

  const [rows, setRows] = useState<UiStringRow[]>([])
  const [coverage, setCoverage] = useState<LanguageCoverage[]>([])
  const [activeJob, setActiveJob] = useState<TranslationJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [missingOnly, setMissingOnly] = useState(false)
  const pollRef = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [strings, cov, jobs] = await Promise.all([
        api.languages.uiStrings(locale),
        api.languages.coverage(),
        api.translations.active(),
      ])
      setRows(strings)
      setCoverage(cov)
      setActiveJob(jobs[0] ?? null)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [locale])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  // Poll while a job is active.
  useEffect(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!activeJob) return
    pollRef.current = window.setInterval(() => {
      void (async () => {
        try {
          const jobs = await api.translations.active()
          setActiveJob(jobs[0] ?? null)
          if (!jobs.length) await refresh()
        } catch { /* ignore */ }
      })()
    }, 2000)
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [activeJob, refresh])

  const currentCoverage = coverage.find(c => c.locale === locale)
  const total = currentCoverage?.total ?? rows.length
  const translated = currentCoverage?.translated ?? rows.filter(r => r.translated).length
  const missing = total - translated

  async function startMissing() {
    const scopeText = 'all languages'
    if (!confirm(
      `Translate all missing strings for ${scopeText}?\n\n` +
      `This will translate every (key, language) pair that has no ` +
      `translation yet. It runs in the background — you can close ` +
      `this panel.`
    )) return
    setError(null)
    try {
      const job = await api.translations.start('missing', null)
      setActiveJob(job)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  async function refreshLocale() {
    if (!confirm(
      `Refresh ${languageName(locale)}?\n\n` +
      `This deletes all ${translated} existing ${languageName(locale)} ` +
      `translations and regenerates them. Manual edits are also lost.`
    )) return
    setError(null)
    try {
      const job = await api.translations.start('refresh', locale)
      setActiveJob(job)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  async function cancelJob() {
    if (!activeJob) return
    try {
      await api.translations.cancel(activeJob.id)
      setActiveJob({ ...activeJob, cancel_requested: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    }
  }

  const visible = missingOnly ? rows.filter(r => !r.translated) : rows

  return (
    <div className="max-w-6xl space-y-4">
      <header>
        <h2 className="text-lg font-medium text-slate-900">Languages</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Manage the English UI dictionary and its translations. English
          is the source of truth — edit it in <code className="rounded bg-slate-100 px-1">ui_strings.py</code> and restart.
        </p>
      </header>

      {/* Top bar */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-slate-600">Language</span>
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              <optgroup label="Promoted">
                {LANGUAGES.filter(l => (PROMOTED_LOCALES as readonly string[]).includes(l.code))
                  .map(l => (
                    <option key={l.code} value={l.code}>
                      {l.native} · {l.english}
                    </option>
                  ))}
              </optgroup>
              <optgroup label="All">
                {LANGUAGES.filter(l => !(PROMOTED_LOCALES as readonly string[]).includes(l.code))
                  .map(l => (
                    <option key={l.code} value={l.code}>
                      {l.native} · {l.english}
                    </option>
                  ))}
              </optgroup>
            </select>
          </label>
          <span className="text-xs text-slate-500">
            {languageNative(locale)} ·{' '}
            <span className="font-mono">{translated}/{total}</span>
            {missing > 0 && (
              <span className="ml-2 text-amber-700">· {missing} missing</span>
            )}
          </span>
          <label className="ml-auto flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={missingOnly}
              onChange={(e) => setMissingOnly(e.target.checked)}
            />
            Show only missing
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void startMissing()}
            disabled={!!activeJob}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Translate missing (all languages)
          </button>
          <button
            onClick={() => void refreshLocale()}
            disabled={!!activeJob || translated === 0}
            className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-800 disabled:opacity-50"
          >
            Refresh {languageName(locale)}
          </button>
        </div>

        {activeJob && <JobBar job={activeJob} onCancel={() => void cancelJob()} />}
        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            {error}
          </div>
        )}
      </div>

      {/* Spreadsheet */}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="grid grid-cols-[16rem_1fr_1fr] border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
          <div className="px-3 py-2">Key</div>
          <div className="border-l border-slate-200 px-3 py-2">English</div>
          <div className="border-l border-slate-200 px-3 py-2">
            {languageNative(locale)}
          </div>
        </div>

        <div className="max-h-[70vh] overflow-y-auto">
          {loading && (
            <div className="py-8 text-center text-sm text-slate-500">Loading…</div>
          )}
          {!loading && visible.length === 0 && (
            <div className="py-8 text-center text-sm text-slate-500">
              {missingOnly ? 'All strings translated for this language.' : 'No strings.'}
            </div>
          )}
          {visible.map((row) => (
            <Row
              key={row.key}
              row={row}
              locale={locale}
              onSaved={(translated) => {
                setRows(rs => rs.map(r =>
                  r.key === row.key ? { ...r, translated } : r,
                ))
              }}
              onDeleted={() => {
                setRows(rs => rs.map(r =>
                  r.key === row.key
                    ? { ...r, translated: null, translator_signature: null, translated_at: null }
                    : r,
                ))
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function JobBar({ job, onCancel }: { job: TranslationJob; onCancel: () => void }) {
  const pct = job.total > 0 ? (job.done / job.total) * 100 : 0
  const scope = job.locale ? languageName(job.locale) : 'all languages'
  const mode = job.mode === 'refresh' ? 'Refreshing' : 'Translating'
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-slate-700">
          {mode} {scope} · <span className="font-mono">{job.done}/{job.total}</span>
          {job.failed > 0 && (
            <span className="ml-2 text-red-700">· {job.failed} failed</span>
          )}
          {job.cancel_requested && (
            <span className="ml-2 text-amber-700">· cancelling…</span>
          )}
        </span>
        <button
          onClick={onCancel}
          disabled={job.cancel_requested}
          className="text-xs text-slate-500 underline hover:text-slate-900 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full bg-slate-900 transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function Row({
  row, locale, onSaved, onDeleted,
}: {
  row: UiStringRow
  locale: string
  onSaved: (translated: string) => void
  onDeleted: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(row.translated ?? '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setDraft(row.translated ?? '')
    setEditing(false)
  }, [row.translated, locale])

  async function save() {
    if (draft.trim() === (row.translated ?? '')) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      await api.languages.setTranslation(row.key, locale, draft)
      onSaved(draft)
      setEditing(false)
    } catch { /* surfaced at panel level via refresh */ }
    finally { setSaving(false) }
  }

  async function del() {
    if (!confirm(`Delete ${locale} translation for ${row.key}?`)) return
    try {
      await api.languages.deleteTranslation(row.key, locale)
      onDeleted()
    } catch { /* ignore */ }
  }

  return (
    <div className="grid grid-cols-[16rem_1fr_1fr] border-b border-slate-100 text-sm hover:bg-slate-50">
      <div className="truncate px-3 py-2 font-mono text-[11px] text-slate-500">
        {row.key}
      </div>
      <div className="border-l border-slate-100 px-3 py-2 text-slate-700">
        {row.english}
      </div>
      <div className="group relative border-l border-slate-100 px-3 py-2">
        {editing ? (
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => void save()}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setDraft(row.translated ?? '')
                setEditing(false)
              }
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void save()
              }
            }}
            rows={2}
            className="w-full resize-y rounded border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none"
            disabled={saving}
          />
        ) : row.translated ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="block w-full text-left text-slate-700 hover:bg-white"
          >
            {row.translated}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-xs text-slate-400 italic hover:text-slate-700"
          >
            — click to translate
          </button>
        )}
        {row.translated && !editing && (
          <button
            onClick={() => void del()}
            className="absolute right-2 top-2 hidden text-[11px] text-slate-400 hover:text-red-600 group-hover:block"
            title="Delete translation"
          >
            ×
          </button>
        )}
      </div>
    </div>
  )
}