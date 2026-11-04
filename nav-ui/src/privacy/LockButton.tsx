import { useState } from 'react'
import { usePrivacy } from './PrivacyContext'

export function LockButton() {
  const { hasPin, lock, setPinAndLock } = usePrivacy()
  const [setupOpen, setSetupOpen] = useState(false)
  const [pin1, setPin1] = useState('')
  const [pin2, setPin2] = useState('')
  const [error, setError] = useState<string | null>(null)

  function onClick() {
    if (hasPin) lock()
    else setSetupOpen(true)
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!/^\d{4}$/.test(pin1)) return setError('PIN must be 4 digits')
    if (pin1 !== pin2) return setError('PINs do not match')
    setPinAndLock(pin1)
    setSetupOpen(false)
    setPin1(''); setPin2(''); setError(null)
  }

  return (
    <>
      <button
        onClick={onClick}
        className="fixed bottom-4 right-4 z-30 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white shadow-md hover:bg-slate-800"
        title={hasPin ? 'Lock session' : 'Set PIN and lock'}
      >
        🔒 Lock
      </button>

      {setupOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
          <form
            onSubmit={submit}
            className="w-full max-w-xs rounded-xl bg-white p-5 shadow-xl"
          >
            <h2 className="text-lg font-medium text-slate-900">Set a session PIN</h2>
            <p className="mt-1 text-xs text-slate-600">
              Four digits. Lives only in this tab. Forgetting it means ending
              the session.
            </p>

            <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-slate-500">
              PIN
            </label>
            <input
              type="password"
              inputMode="numeric"
              maxLength={4}
              value={pin1}
              onChange={(e) => setPin1(e.target.value.replace(/\D/g, '').slice(0, 4))}
              autoFocus
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-widest"
            />

            <label className="mt-3 block text-xs font-medium uppercase tracking-wide text-slate-500">
              Confirm
            </label>
            <input
              type="password"
              inputMode="numeric"
              maxLength={4}
              value={pin2}
              onChange={(e) => setPin2(e.target.value.replace(/\D/g, '').slice(0, 4))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-widest"
            />

            {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setSetupOpen(false); setPin1(''); setPin2(''); setError(null)
                }}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pin1.length !== 4 || pin1 !== pin2}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                Set PIN &amp; lock
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}