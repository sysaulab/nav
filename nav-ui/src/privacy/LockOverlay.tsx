import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePrivacy } from './PrivacyContext'
import { api } from '../api'

export function LockOverlay() {
  const { locked, unlock, clearPin } = usePrivacy()
  const navigate = useNavigate()
  const [entry, setEntry] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [attempts, setAttempts] = useState(0)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [ending, setEnding] = useState(false)

  useEffect(() => {
    if (locked) {
      setEntry(''); setError(null); setConfirmEnd(false)
    }
  }, [locked])

  useEffect(() => {
    if (!locked || entry.length !== 4) return
    if (unlock(entry)) {
      setEntry(''); setError(null); setAttempts(0)
    } else {
      setError('Wrong PIN')
      setAttempts((n) => n + 1)
      setEntry('')
    }
  }, [entry, locked, unlock])

  async function endSession() {
    setEnding(true)
    try {
      const active = await api.interviews.active()
      if (active) await api.interviews.end(active.id)
    } catch {
      // session may already be gone — that's fine
    } finally {
      clearPin()
      navigate('/')
    }
  }

  if (!locked) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-100/80 backdrop-blur-xl">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
        <div className="text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-2xl">
            🔒
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-900">Session locked</h2>
          <p className="mt-1 text-sm text-slate-600">Enter your 4-digit PIN</p>
        </div>

        <div className="mt-5 flex justify-center gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className={`h-3 w-3 rounded-full ${
                i < entry.length ? 'bg-slate-900' : 'bg-slate-200'
              }`}
            />
          ))}
        </div>

        {error && (
          <p className="mt-2 text-center text-xs text-red-600">
            {error}{attempts > 1 && ` (${attempts} attempts)`}
          </p>
        )}

        <div className="mt-5 grid grid-cols-3 gap-2">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => (
            <button
              key={d}
              onClick={() => { setError(null); setEntry((e) => (e + d).slice(0, 4)) }}
              className="rounded-lg border border-slate-200 bg-white py-3 text-lg font-medium hover:bg-slate-50"
            >
              {d}
            </button>
          ))}
          <button
            onClick={() => { setEntry(''); setError(null) }}
            className="rounded-lg border border-slate-200 bg-white py-3 text-xs text-slate-500 hover:bg-slate-50"
          >
            Clear
          </button>
          <button
            onClick={() => { setError(null); setEntry((e) => (e + '0').slice(0, 4)) }}
            className="rounded-lg border border-slate-200 bg-white py-3 text-lg font-medium hover:bg-slate-50"
          >
            0
          </button>
          <button
            onClick={() => { setError(null); setEntry((e) => e.slice(0, -1)) }}
            className="rounded-lg border border-slate-200 bg-white py-3 text-sm text-slate-500 hover:bg-slate-50"
          >
            ⌫
          </button>
        </div>

        <div className="mt-5 text-center">
          {!confirmEnd ? (
            <button
              onClick={() => setConfirmEnd(true)}
              className="text-xs text-slate-500 hover:text-red-600"
            >
              Forgot PIN?
            </button>
          ) : (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-left">
              <p className="text-xs text-red-900">
                Resetting requires ending the session. The conversation and
                any uploaded documents will be discarded.
              </p>
              <div className="mt-2 flex justify-end gap-2">
                <button
                  onClick={() => setConfirmEnd(false)}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void endSession()}
                  disabled={ending}
                  className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
                >
                  {ending ? 'Ending…' : 'End session'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}