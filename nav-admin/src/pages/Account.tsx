// nav-admin/src/pages/Account.tsx
import { useEffect, useState } from 'react'
import { api, ApiError, setToken, type TokenStatus } from '../api'

const inputCls =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none'

const MIN_LEN = 16

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

export default function Account() {
  const [status, setStatus] = useState<TokenStatus | null>(null)
  const [statusErr, setStatusErr] = useState<string | null>(null)

  const [current, setCurrent] = useState('')
  const [newTok, setNewTok] = useState('')
  const [confirm, setConfirm] = useState('')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  function refreshStatus() {
    api.auth
      .status()
      .then(setStatus)
      .catch((e) =>
        setStatusErr(e instanceof ApiError ? e.detail : (e as Error).message),
      )
  }

  useEffect(() => {
    refreshStatus()
  }, [])

  const tooShort = newTok.length > 0 && newTok.length < MIN_LEN
  const mismatch = confirm.length > 0 && newTok !== confirm
  const sameAsCurrent = newTok.length > 0 && newTok === current
  const canSubmit =
    current.length > 0 &&
    newTok.length >= MIN_LEN &&
    newTok === confirm &&
    !sameAsCurrent &&
    !saving

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      await api.auth.changeToken(current, newTok, confirm)
      setToken(newTok)
      setCurrent('')
      setNewTok('')
      setConfirm('')
      setSuccess(true)
      setTimeout(() => setSuccess(false), 5000)
      refreshStatus()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <h2 className="text-lg font-medium text-slate-900">Account</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Manage the admin token used to sign into this console. Changing
          it logs out every other session that holds the previous token
          — including other browser tabs on this machine.
        </p>
      </header>

      {statusErr && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {statusErr}
        </div>
      )}

      {status && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-900">
                Current token source
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {status.source === 'database' && (
                  <>A custom token was set through this console.</>
                )}
                {status.source === 'env' && (
                  <>
                    Using <code className="rounded bg-slate-100 px-1">NAVIGATOR_ADMIN_TOKEN</code>{' '}
                    from the deployment's environment. Rotate it here to
                    stop depending on the env value.
                  </>
                )}
                {status.source === 'none' && (
                  <>
                    Admin is not configured. Set{' '}
                    <code className="rounded bg-slate-100 px-1">
                      NAVIGATOR_ADMIN_TOKEN
                    </code>{' '}
                    in the deployment to enable this console.
                  </>
                )}
              </div>
            </div>
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-[11px] font-medium ${
                status.source === 'database'
                  ? 'bg-emerald-100 text-emerald-700'
                  : status.source === 'env'
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-slate-100 text-slate-600'
              }`}
            >
              {status.source}
            </span>
          </div>
        </div>
      )}

      <form
        onSubmit={submit}
        className="rounded-xl border border-slate-200 bg-white p-5 space-y-4"
      >
        <Field label="Current token">
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={inputCls}
          />
        </Field>

        <Field
          label="New token"
          hint={`Minimum ${MIN_LEN} characters. This is the only barrier between the internet and your directory — pick something long.`}
        >
          <input
            type="password"
            autoComplete="new-password"
            value={newTok}
            onChange={(e) => setNewTok(e.target.value)}
            className={inputCls}
          />
        </Field>

        <Field label="Confirm new token">
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={inputCls}
          />
        </Field>

        {tooShort && (
          <p className="text-xs text-red-700">
            New token must be at least {MIN_LEN} characters.
          </p>
        )}
        {mismatch && (
          <p className="text-xs text-red-700">
            New token and confirmation do not match.
          </p>
        )}
        {sameAsCurrent && (
          <p className="text-xs text-red-700">
            New token is identical to the current one.
          </p>
        )}

        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            {error}
          </div>
        )}
        {success && (
          <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">
            Token changed. Your session is still active with the new
            token. Other sessions will be logged out on their next request.
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-2">
          <p className="text-[11px] text-slate-500">
            Write the new token down somewhere safe — we don't display it
            again after this form.
          </p>
          <button
            type="submit"
            disabled={!canSubmit}
            className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Change token'}
          </button>
        </div>
      </form>

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
        <p className="font-medium text-slate-800">If you forget the token</p>
        <p className="mt-1">
          Set <code className="rounded bg-slate-200 px-1">NAVIGATOR_ADMIN_TOKEN</code>{' '}
          in the deployment config and delete any database override:
        </p>
        <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">
{`DELETE FROM app_setting WHERE key = 'auth.admin_token';
# then restart the container`}
        </pre>
        <p className="mt-2">
          A database override always wins over the env value, so deleting
          the row is what restores the env token as the effective credential.
        </p>
      </div>
    </div>
  )
}