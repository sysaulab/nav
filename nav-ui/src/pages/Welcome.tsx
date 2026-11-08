import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AddressAutocomplete } from '../components/AddressAutocomplete'
import { Pill, type PillTone } from '../components/Pill'
import logoUrl from '../assets/logo.svg'
import type { GeocodeSuggestion } from '../types'

export default function Welcome() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<GeocodeSuggestion | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleSelect(s: GeocodeSuggestion) {
    setSelected(s)
    setQuery(s.display_name)
    setError(null)
  }

  function start() {
    if (!selected) return
    // Store the resolved location to be picked up by the Interview page
    sessionStorage.setItem('pending_location', JSON.stringify(selected))
    navigate('/interview')
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-md">
        <header className="mb-8 text-center">
          <img
            src={logoUrl}
            alt="Local Resource Navigator"
            className="mx-auto h-12 w-auto"
          />
          <h1 className="mt-4 text-3xl font-semibold text-slate-900">
            Welcome
          </h1>
          <p className="mt-2 text-slate-600">
            Talk through your situation, upload documents, and get a personalized plan.
          </p>
        </header>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-medium text-slate-900">Where are you located?</h2>
          <p className="mt-2 text-sm text-slate-600">
            We use this to find services near you. Not all addresses are in the map — if you can't find yours, pick one close by (e.g. the odd house across the street). Precise location is not required.
          </p>

          <div className="mt-4">
            <AddressAutocomplete
              value={query}
              onChange={(v) => {
                setQuery(v)
                setSelected(null)
              }}
              onSelect={handleSelect}
              placeholder="e.g. M5V 2T6 or 123 Queen St W"
              autoFocus
            />
          </div>

          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

          <div className="mt-6 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
            <p><strong>Note:</strong> Sessions time out after 15 minutes of inactivity during chat or upload. Everything is wiped when the session ends.</p>
          </div>

          <button
            onClick={start}
            disabled={!selected}
            className="mt-6 w-full rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Start Session
          </button>
        </div>

        <SystemStatus />
      </div>
    </main>
  )
}

type HealthState = 'loading' | 'ok' | 'down'

function SystemStatus() {
  const [maestro, setMaestro] = useState<HealthState>('loading')
  const [ingest, setIngest] = useState<HealthState>('loading')
  const [geocoder, setGeocoder] = useState<HealthState>('loading')
  const [ollama, setOllama] = useState<HealthState>('loading')
  const [sql, setSql] = useState<HealthState>('loading')

  useEffect(() => {
    let alive = true

    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setMaestro(d.status === 'ok' ? 'ok' : 'down')
      })
      .catch(() => alive && setMaestro('down'))

    fetch('/api/health/ingest')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setIngest(d.ok ? 'ok' : 'down')
      })
      .catch(() => alive && setIngest('down'))

    fetch('/api/health/geocoder')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setGeocoder(d.ok ? 'ok' : 'down')
      })
      .catch(() => alive && setGeocoder('down'))

    fetch('/api/health/ollama')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setOllama(d.ok ? 'ok' : 'down')
      })
      .catch(() => alive && setOllama('down'))

    fetch('/api/health/sql')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setSql(d.ok ? 'ok' : 'down')
      })
      .catch(() => alive && setSql('down'))

    return () => { alive = false }
  }, [])

  return (
    <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
      <Pill tone={toneFor(maestro)} label="nav" />
      <Pill tone={toneFor(ingest)} label="doc" />
      <Pill tone={toneFor(geocoder)} label="geo" />
      <Pill tone={toneFor(ollama)} label="llm" />
      <Pill tone={toneFor(sql)} label="sql" />
    </div>
  )
}

function toneFor(state: HealthState): PillTone {
  if (state === 'ok') return 'ok'
  if (state === 'down') return 'error'
  return 'neutral'
}