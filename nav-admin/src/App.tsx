import { useState } from 'react'
import { AuthProvider, useAuth } from './auth'
import { ApiError } from './api'
import Models from './pages/Models'

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}

function Shell() {
  const { authed, loading, logout } = useAuth()
  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-500">Loading…</p>
      </main>
    )
  }
  if (!authed) return <LoginGate />
  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-slate-900">
              Navigator Admin
            </h1>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
              models
            </span>
          </div>
          <button
            onClick={logout}
            className="text-xs text-slate-500 hover:text-slate-900"
          >
            Sign out
          </button>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-6">
        <Models />
      </div>
    </main>
  )
}

function LoginGate() {
  const { submitToken } = useAuth()
  const [token, setLocalToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!token.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await submitToken(token.trim())
    } catch (e) {
      if (e instanceof ApiError) {
        setError(
          e.status === 503
            ? 'Admin is not configured on this server.'
            : 'Wrong token.',
        )
      } else {
        setError((e as Error).message)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6"
      >
        <h1 className="text-lg font-semibold text-slate-900">
          Navigator Admin
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          Enter the admin token set by your operator.
        </p>
        <input
          type="password"
          autoFocus
          value={token}
          onChange={(e) => setLocalToken(e.target.value)}
          placeholder="Admin token"
          className="mt-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || !token.trim()}
          className="mt-4 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Continue'}
        </button>
      </form>
    </main>
  )
}