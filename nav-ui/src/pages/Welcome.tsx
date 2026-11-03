import { useEffect, useState } from 'react'
import Card from '../components/Card'
import { Pill, type PillTone } from '../components/Pill'
import logoUrl from '../assets/logo.svg'

export default function Welcome() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-4xl">
        <header className="mb-10 text-center">
          <img
            src={logoUrl}
            alt="Local Resource Navigator"
            className="mx-auto h-12 w-auto"
          />
          <h1 className="text-4xl font-semibold text-slate-900">
            &nbsp;
          </h1>
          <p className="mt-3 text-slate-600">
            Talk through your situation, upload supporting documents, and get a
            personalized plan — or manage the local resource directory.
          </p>
        </header>

        <div className="grid gap-6 md:grid-cols-2">
          <Card
            to="/interview"
            title="Help a customer"
            badge="Ready"
            description="Guided conversation, document upload, and a personalized plan. One session at a time; everything is wiped when the session ends."
          />
          <Card
            to="/database"
            title="Manage resources"
            badge="Ready"
            description="Browse and edit the HSDS directory. Set geographic coordinates so services can be fenced by bbox or radius."
          />
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

  // Endpoints as reported by the backend. The pills display what maestro
  // actually dialed — not a hardcoded string — so a wrong env var shows up
  // as the wrong hostname instead of hiding behind a generic red dot.
  const [ingestEndpoint, setIngestEndpoint] = useState<string | null>(null)
  const [geocoderEndpoint, setGeocoderEndpoint] = useState<string | null>(null)
  const [ollamaEndpoint, setOllamaEndpoint] = useState<string | null>(null)
  const [ollamaModel, setOllamaModel] = useState<string | null>(null)

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
        if (typeof d.endpoint === 'string') setIngestEndpoint(d.endpoint)
      })
      .catch(() => alive && setIngest('down'))

    fetch('/api/health/geocoder')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setGeocoder(d.ok ? 'ok' : 'down')
        if (typeof d.endpoint === 'string') setGeocoderEndpoint(d.endpoint)
      })
      .catch(() => alive && setGeocoder('down'))

    fetch('/api/health/ollama')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setOllama(d.ok ? 'ok' : 'down')
        if (typeof d.endpoint === 'string') setOllamaEndpoint(d.endpoint)
        if (typeof d.model === 'string') setOllamaModel(d.model)
      })
      .catch(() => alive && setOllama('down'))

    return () => { alive = false }
  }, [])

  const llmDetail = ollamaEndpoint
    ? ollamaModel
      ? `${shortenEndpoint(ollamaEndpoint)} · ${ollamaModel}`
      : shortenEndpoint(ollamaEndpoint)
    : 'loading…'

  return (
    <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
      {/* Maestro is reached via the nginx /api proxy on whatever origin the
          browser loaded this page from — so the honest "endpoint" is our
          own host, not the container's internal bind address. */}
      <Pill
        tone={toneFor(maestro)}
        label="nav"
        detail={window.location.host}
      />
      <Pill
        tone={toneFor(ingest)}
        label="doc"
        detail={ingestEndpoint ? shortenEndpoint(ingestEndpoint) : 'loading…'}
      />
      <Pill
        tone={toneFor(geocoder)}
        label="geo"
        detail={geocoderEndpoint ? shortenEndpoint(geocoderEndpoint) : 'loading…'}
      />
      <Pill tone={toneFor(ollama)} label="llm" detail={llmDetail} />
    </div>
  )
}

/** Strip scheme and a trailing slash for compact display.
 *  Keeps host:port and any path — both are diagnostic. */
function shortenEndpoint(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '')
}

function toneFor(state: HealthState): PillTone {
  if (state === 'ok') return 'ok'
  if (state === 'down') return 'error'
  return 'neutral'
}