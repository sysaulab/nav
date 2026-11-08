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
            Talk through your situation, upload documents, and get a
            personalized plan.
          </p>
        </header>

        <div className="grid gap-6 md:grid-cols-2">
          <div className="md:col-span-2">
            <Card
              to="/interview"
              title="Get Help!"
              badge="Ready"
              description="Guided conversation, document upload, and a personalized plan. One session at a time; everything is wiped when the session ends."
            />
          </div>
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