import { useState } from 'react'
import { AuthProvider, useAuth } from './auth'
import { ApiError } from './api'
import Models from './pages/Models'
import Prompt from './pages/Prompt'
import Account from './pages/Account'
import DirectoryTree from './pages/DirectoryTree'
import Locations from './pages/Locations'
import Languages from './pages/Languages'
import Backup from './pages/Backup'

type Tab =
  | 'directory'
  | 'locations'
  | 'languages'
  | 'backup'
  | 'models'
  | 'prompt'
  | 'account'

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}

function Shell() {
  const { authed, loading, logout } = useAuth()
  const [tab, setTab] = useState<Tab>('directory')

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
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <h1 className="text-sm font-semibold text-slate-900">
            Navigator Admin
          </h1>
          <button
            onClick={logout}
            className="text-xs text-slate-500 hover:text-slate-900"
          >
            Sign out
          </button>
        </div>
      </header>
      <div className="mx-auto flex max-w-6xl gap-6 px-6 py-6">
        <aside className="w-44 shrink-0">
          <nav className="space-y-1">
            <NavItem
              active={tab === 'directory'}
              onClick={() => setTab('directory')}
            >
              Directory
            </NavItem>
            <NavItem
              active={tab === 'locations'}
              onClick={() => setTab('locations')}
            >
              Locations
            </NavItem>
            <NavItem
              active={tab === 'languages'}
              onClick={() => setTab('languages')}
            >
              Languages
            </NavItem>
            <NavItem
              active={tab === 'backup'}
              onClick={() => setTab('backup')}
            >
              Backup
            </NavItem>
            <div className="my-2 border-t border-slate-200" />
            <NavItem active={tab === 'models'} onClick={() => setTab('models')}>
              Models
            </NavItem>
            <NavItem active={tab === 'prompt'} onClick={() => setTab('prompt')}>
              Prompt
            </NavItem>
            <NavItem
              active={tab === 'account'}
              onClick={() => setTab('account')}
            >
              Account
            </NavItem>
          </nav>
        </aside>
        <section className="min-w-0 flex-1">
          {tab === 'directory' && <DirectoryTree />}
          {tab === 'locations' && <Locations />}
          {tab === 'languages' && <Languages />}
          {tab === 'backup' && <Backup />}
          {tab === 'models' && <Models />}
          {tab === 'prompt' && <Prompt />}
          {tab === 'account' && <Account />}
        </section>
      </div>
    </main>
  )
}

function NavItem({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`block w-full rounded-lg px-3 py-1.5 text-left text-sm ${
        active
          ? 'bg-slate-900 text-white'
          : 'text-slate-600 hover:bg-slate-100'
      }`}
    >
      {children}
    </button>
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