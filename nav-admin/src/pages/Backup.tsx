import { useRef, useState } from 'react'
import { api, ApiError } from '../api'

export default function Backup() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<Record<string, number> | null>(null)

  async function handleExport() {
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await api.backup.exportDatabase()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setExportError((e as Error).message)
    } finally {
      setExporting(false)
    }
  }

  function openImportPicker() {
    fileInputRef.current?.click()
  }

  async function handleImportFile(file: File) {
    setImportError(null)
    setImportResult(null)

    let summary = ''
    try {
      const text = await file.text()
      const payload = JSON.parse(text) as {
        format_version?: string
        tables?: Record<string, unknown>
      }
      if (!payload.tables) {
        setImportError('File does not contain a "tables" object')
        return
      }
      const lines = Object.entries(payload.tables).map(([k, v]) =>
        `  ${k}: ${Array.isArray(v) ? v.length : '?'}`,
      )
      summary = `\n\nFormat: ${payload.format_version ?? 'unknown'}\n${lines.join('\n')}`
    } catch (e) {
      setImportError(`Not a valid JSON backup: ${(e as Error).message}`)
      return
    }

    const confirmed = window.confirm(
      `Replace all directory data, operator settings, and UI translations ` +
      `with the contents of "${file.name}"?` +
      summary +
      '\n\nThis cannot be undone. Active sessions are preserved.',
    )
    if (!confirmed) return

    setImporting(true)
    try {
      const result = await api.backup.importDatabase(file)
      setImportResult(result.counts)
    } catch (e) {
      if (e instanceof ApiError) {
        setImportError(e.detail)
      } else {
        setImportError((e as Error).message)
      }
    } finally {
      setImporting(false)
    }
  }

  const totalImported = importResult
    ? Object.values(importResult).reduce((a, b) => a + b, 0)
    : null

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <h2 className="text-lg font-medium text-slate-900">Backup & Restore</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Download a snapshot of the directory, operator settings, and UI
          translations, or restore from a previous backup. Active sessions
          are not included.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-medium text-slate-900">Export</h3>
          <p className="mt-1 text-xs text-slate-500">
            Download a complete snapshot of organizations, locations,
            services, operator settings, and UI translations.
          </p>
          {exportError && (
            <div className="mt-3 rounded bg-red-50 p-2 text-xs text-red-800">
              {exportError}
            </div>
          )}
          <button
            onClick={() => void handleExport()}
            disabled={exporting}
            className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {exporting ? 'Preparing…' : 'Download JSON'}
          </button>
        </section>

        <section className="rounded-xl border border-red-200 bg-red-50 p-5">
          <h3 className="text-sm font-medium text-red-900">Restore</h3>
          <p className="mt-1 text-xs text-red-700">
            Replace the entire directory, operator settings, and UI
            translations with a previous backup. This is destructive and
            cannot be undone.
          </p>
          
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (fileInputRef.current) fileInputRef.current.value = ''
              if (f) void handleImportFile(f)
            }}
          />
          
          {importError && (
            <div className="mt-3 rounded bg-red-100 p-2 text-xs text-red-800 border border-red-200">
              {importError}
            </div>
          )}
          
          <button
            onClick={openImportPicker}
            disabled={importing}
            className="mt-4 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
          >
            {importing ? 'Restoring…' : 'Upload JSON'}
          </button>
        </section>
      </div>

      {importResult && (
        <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <h3 className="text-sm font-medium text-emerald-900">
            Restore Complete — {totalImported ?? 0} rows
          </h3>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs text-emerald-800">
            {Object.entries(importResult).map(([k, v]) => (
              <li key={k} className="flex justify-between border-b border-emerald-100 pb-0.5">
                <span>{k}</span>
                <span className="font-bold">{v}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}