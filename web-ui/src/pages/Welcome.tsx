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

function SystemStatus() {
  const [maestro, setMaestro] = useState<'loading' | 'ok' | 'down'>('loading')
  const [ingest, setIngest] = useState<'loading' | 'ok' | 'down'>('loading')
  const [geocoder, setGeocoder] = useState<'loading' | 'ok' | 'down'>('loading')
  const [ollama, setOllama] = useState<'loading' | 'ok' | 'down'>('loading')
  const [ollamaModel, setOllamaModel] = useState<string | null>(null)

  useEffect(() => {
    let alive = true

    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => alive && setMaestro(d.status === 'ok' ? 'ok' : 'down'))
      .catch(() => alive && setMaestro('down'))

    fetch('/api/health/ingest')
      .then((r) => r.json())
      .then((d) => alive && setIngest(d.ok ? 'ok' : 'down'))
      .catch(() => alive && setIngest('down'))

    fetch('/api/health/geocoder')
      .then((r) => r.json())
      .then((d) => alive && setGeocoder(d.ok ? 'ok' : 'down'))
      .catch(() => alive && setGeocoder('down'))

    fetch('/api/health/ollama')
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return
        setOllama(d.ok ? 'ok' : 'down')
        if (typeof d.model === 'string') setOllamaModel(d.model)
      })
      .catch(() => alive && setOllama('down'))

    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
      <Pill tone={toneFor(maestro)} label="nav" detail="localhost:8001" />
      <Pill tone={toneFor(ingest)}  label="doc" detail="localhost:8000/ingest" />
      <Pill tone={toneFor(geocoder)} label="geo" detail="localhost:8080" />
      <Pill
        tone={toneFor(ollama)}
        label="llm"
        detail={
          ollamaModel ? `localhost:11434 · ${ollamaModel}` : 'localhost:11434'
        }
      />
    </div>
  )
}

function toneFor(state: 'loading' | 'ok' | 'down'): PillTone {
  if (state === 'ok') return 'ok'
  if (state === 'down') return 'error'
  return 'neutral'
}