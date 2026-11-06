// web-ui/src/pages/Interview.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, isSessionError } from '../api'
import { Pill, type PillTone } from '../components/Pill'
import type {
  ChatItem, ChatMessage, ContextPrompt, DocumentMeta, GeocodeSuggestion,
  InterviewSession, ServiceCard, SessionLocation,
} from '../types'
import FileDropzone from '../components/FileDropzone'
import { matchesAccept } from '../util/files.tsx'
import * as React from 'react'
import { usePrivacy } from '../privacy/PrivacyContext'
import { SessionClock } from '../components/SessionClock'

type Upload = { id: string; filename: string; pct: number }

export default function Interview() {
  const navigate = useNavigate()
  const { clearPin } = usePrivacy()
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [docs, setDocs] = useState<DocumentMeta[]>([])
  const [context, setContext] = useState<ContextPrompt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sessionExpired, setSessionExpired] = useState(false)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [chat, setChat] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)

  // Final plan
  const [plan, setPlan] = useState<string | null>(null)
  const [planning, setPlanning] = useState(false)
  const [copied, setCopied] = useState(false)
  const [exportingDocx, setExportingDocx] = useState(false)

  // Location editing (re-open the gate mid-session)
  const [editingLocation, setEditingLocation] = useState(false)

  /** Route a caught error: session-gone goes to the modal, everything else
   * to the error banner. Returns true if it was a session error. */
  const handleApiError = useCallback((e: unknown): boolean => {
    if (isSessionError(e)) {
      setSessionExpired(true)
      return true
    }
    setError((e as Error).message)
    return false
  }, [])


  
  // ── bootstrap ─────────────────────────────────────────
  useEffect(() => {
    let live = true
    api.interviews.createOrResume()
      .then((s) => { if (live) setSession(s) })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])

  const refresh = useCallback(async (sid: string) => {
    try {
      const [d, c] = await Promise.all([
        api.interviews.documents.list(sid),
        api.interviews.contextPrompt(sid),
      ])
      setDocs(d)
      setContext(c)
    } catch (e) {
      handleApiError(e)
    }
  }, [handleApiError])

  useEffect(() => {
    if (session) void refresh(session.id)
  }, [session, refresh])

  // ── upload ────────────────────────────────────────────
const ACCEPT =
  '.rtf,.pdf,.txt,.md,.docx,.odt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,.xlsx,.pptx'

const BLOCKED_LEGACY: Record<string, string> = {
  '.doc': '.docx',
  '.xls': '.xlsx',
  '.ppt': '.pptx',
}

function legacyOfficeHint(filename: string): string | null {
  const i = filename.lastIndexOf('.')
  if (i < 0) return null
  const ext = filename.slice(i).toLowerCase()
  const replacement = BLOCKED_LEGACY[ext]
  return replacement
    ? `${filename}: ${ext} (Office 97-2003) is not supported — re-save as ${replacement} and re-upload.`
    : null
}

async function verifyExpired() {
  if (!session) return
  try {
    // Any authenticated GET refreshes the server deadline. If it succeeds,
    // the deadline slides and the pill disappears on the next tick.
    await api.interviews.location(session.id)
  } catch (e) {
    if (isSessionError(e)) setSessionExpired(true)
  }
}

// ── helpers ───────────────────────────────────────────
/** Local-only id for in-flight uploads (never sent to the backend). */
function newUid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `u_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}




async function onFiles(files: File[]) {
  if (!session || files.length === 0) return
  setError(null)
  try {
    const accepted = files.filter((f) => matchesAccept(f, ACCEPT))
    const rejectedFiles = files.filter((f) => !matchesAccept(f, ACCEPT))

    if (accepted.length === 0) {
      const hints = rejectedFiles
        .map((f) => legacyOfficeHint(f.name))
        .filter((h): h is string => h !== null)
      setError(
        hints.length > 0
          ? hints.join(' · ')
          : 'Unsupported file type. Accepted: PDF, Office (OOXML), images, plain text.',
      )
      return
    }
    if (rejectedFiles.length > 0) {
      const hints = rejectedFiles
        .map((f) => legacyOfficeHint(f.name))
        .filter((h): h is string => h !== null)
      setError(
        hints.length > 0
          ? hints.join(' · ')
          : `${rejectedFiles.length} file(s) skipped — unsupported type`,
      )
    }


    for (const f of accepted) {
      const id = newUid()
      setUploads((u) => [...u, { id, filename: f.name, pct: 0 }])
      try {
        await api.interviews.documents.upload(session.id, f, (pct) =>
          setUploads((u) => u.map((x) => (x.id === id ? { ...x, pct } : x))),
        )
      } catch (e) {
        if (!handleApiError(e)) {
          setError(`${f.name}: ${(e as Error).message}`)
        }
      } finally {
        await refresh(session.id)
        setUploads((u) => u.filter((x) => x.id !== id))
      }
    }
  } catch (e) {
    setError((e as Error).message ?? String(e))
  }
}

  async function removeDoc(id: string) {
    if (!session) return
    try {
      await api.interviews.documents.remove(session.id, id)
      await refresh(session.id)
    } catch (e) {
      handleApiError(e)
    }
  }

  async function endSession() {
    if (!session) return
    if (!confirm('End this session? Documents and chat history will be discarded.')) return
    try {
      await api.interviews.end(session.id)
      clearPin()
      setSession(null)
      setDocs([])
      setContext(null)
      setChat([])
      setPlan(null)
      navigate('/')
    } catch (e) {
      // If the session was already gone, the user's intent is satisfied —
      // take them home rather than showing the "expired" modal they were
      // already navigating away from.
      if (isSessionError(e)) {
        navigate('/')
      } else {
        setError((e as Error).message)
      }
    }
  }

  // ── chat ──────────────────────────────────────────────
  async function send() {
    if (!session || !input.trim() || streaming) return
    const userMsg: ChatMessage = { role: 'user', content: input.trim() }

    // Only `message` items are part of the wire history; cards stay local.
    const priorMessages: ChatMessage[] = chat
      .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
      .map((i) => ({ role: i.role, content: i.content }))
    const apiMessages = [...priorMessages, userMsg]

    setChat((prev) => [
      ...prev,
      { kind: 'message', role: 'user', content: userMsg.content },
    ])
    setInput('')
    setStreaming(true)
    setError(null)
    setPlan(null)

    let assistantBuf = ''

    const appendChunk = (text: string) => {
      assistantBuf += text
      const buf = assistantBuf
      setChat((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.kind === 'message' && last.role === 'assistant') {
          return [...prev.slice(0, -1), { kind: 'message', role: 'assistant', content: buf }]
        }
        return [...prev, { kind: 'message', role: 'assistant', content: buf }]
      })
    }

    const insertCard = (card: ServiceCard) => {
      // Close the current assistant segment (already in state), then append
      // the card. The next content chunk starts a fresh assistant message.
      assistantBuf = ''
      setChat((prev) => [...prev, { kind: 'card', card }])
    }

    try {
      await api.interviews.chat(session.id, apiMessages, (raw) => {
        const obj = raw as {
          message?: { content?: string }
          event?: string
          index?: number
          service?: ServiceCard['service']
          error?: string
        }
        if (obj.error) { setError(obj.error); return }
        if (obj.message?.content) appendChunk(obj.message.content)
        if (obj.event === 'service_card' && obj.service && obj.index !== undefined) {
          insertCard({ index: obj.index, service: obj.service })
        }
      })
    } catch (e) {
      handleApiError(e)
    } finally {
      setStreaming(false)
    }
  }

  // ── finalize ──────────────────────────────────────────
  async function finalize() {
    if (!session || planning || streaming) return
    const priorMessages: ChatMessage[] = chat
      .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
      .map((i) => ({ role: i.role, content: i.content }))

    setPlanning(true)
    setPlan('')
    setError(null)
    let acc = ''
    try {
      await api.interviews.finalize(session.id, priorMessages, (raw) => {
        const obj = raw as { message?: { content?: string }; error?: string }
        if (obj.error) { setError(obj.error); return }
        if (obj.message?.content) {
          acc += obj.message.content
          setPlan(acc)
        }
      })
    } catch (e) {
      handleApiError(e)
    } finally {
      setPlanning(false)
    }
  }

  // ── plan actions ──────────────────────────────────────
  async function copyPlan() {
    if (plan === null || !plan) return
    try {
      await navigator.clipboard.writeText(plan)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = plan
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* ignore */ }
      ta.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  function downloadPlan() {
    if (plan === null || !plan) return
    const blob = new Blob([plan], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `action-plan-${session?.id.slice(0, 8) ?? 'session'}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  async function downloadDocx() {
    if (!plan) return
    setExportingDocx(true)
    setError(null)
    const stem = `action-plan-${session?.id.slice(0, 8) ?? 'session'}`
    try {
      const res = await fetch('/api/export/docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown: plan, filename: stem }),
      })
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${stem}.docx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setExportingDocx(false)
    }
  }

  // ── render ────────────────────────────────────────────
  if (sessionExpired) {
    return <SessionExpiredModal />
  }

  if (!session) {
    return (
      <main className="min-h-screen bg-slate-50 p-8">
        <div className="mx-auto max-w-3xl">
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">← Back</Link>
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-8 text-center">
            <p className="text-slate-600">Starting a session…</p>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </div>
        </div>
      </main>
    )
  }

  // ── Location gate: first-time entry OR mid-session edit ──
  if (!session.postal_code || editingLocation) {
    return (
      <LocationGate
        session={session}
        onLocated={(loc) => {
          setSession({
            ...session,
            postal_code: loc.postal_code,
            origin_display_name: loc.origin_display_name,
          })
          setEditingLocation(false)
          // Nearby services are baked into the system prompt per turn, so a
          // location change invalidates any existing plan. Clear it so the
          // Finish button reappears and the user can regenerate.
          setPlan(null)
        }}
        onCancel={
          session.postal_code
            ? () => setEditingLocation(false)
            : undefined
        }
        onSessionError={() => setSessionExpired(true)}
      />
    )
  }

  const includedIds = new Set(context?.included.map((d) => d.id) ?? [])
  const hasMessages = chat.some((i) => i.kind === 'message')
  const canFinish = !planning && !streaming && hasMessages
  const planHasContent = !!plan && !planning

  return (
    <main className="min-h-screen bg-slate-50 p-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setEditingLocation(true)}
              disabled={planning}
              className="text-sm text-slate-500 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              ← Change location
            </button>
            <span className="text-xs text-slate-400">|</span>
            <span className="text-xs text-slate-500">
              Location:{' '}
              <span className="text-slate-700">
                {session.origin_display_name || session.postal_code}
              </span>
            </span>
            <SessionClock
              seedExpiresAt={session.expires_at}
              onExpired={() => void verifyExpired()}
            />
          </div>
          <div className="flex items-center gap-2">
            {!planHasContent && (
              <button
                onClick={() => void finalize()}
                disabled={!canFinish}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {planning ? 'Finishing…' : 'Finish'}
              </button>
            )}
            <button
              onClick={() => void endSession()}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              End session
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {plan !== null && (
          <section className="mt-6 rounded-xl border-2 border-emerald-300 bg-emerald-50 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-medium text-emerald-900">Action plan</h2>
                {planning && (
                  <span className="text-xs text-emerald-700">Generating…</span>
                )}
              </div>
              {!planning && plan && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void copyPlan()}
                    className="rounded-lg border border-emerald-400 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
                    aria-live="polite"
                  >
                    {copied ? 'Copied!' : 'Copy'}
                  </button>
                  <button
                    type="button"
                    onClick={downloadPlan}
                    className="rounded-lg border border-emerald-400 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
                  >
                    📄 Markdown
                  </button>
                  <button
                    type="button"
                    onClick={() => void downloadDocx()}
                    disabled={exportingDocx}
                    className="rounded-lg border border-emerald-400 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
                  >
                    {exportingDocx ? '📄 Preparing…' : '📄 Office'}
                  </button>
                </div>
              )}
            </div>

            {plan ? (
              <article className="prose prose-sm prose-slate mt-3 max-w-none prose-headings:font-semibold prose-headings:text-slate-900 prose-a:text-emerald-700 prose-code:text-emerald-800 prose-pre:bg-slate-900">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{plan}</ReactMarkdown>
              </article>
            ) : (
              !planning && (
                <p className="mt-3 text-sm text-emerald-950">No content generated.</p>
              )
            )}

            <div className="mt-3 flex justify-end gap-3 text-xs">
              {!planning && (
                <>
                  <button
                    onClick={() => void finalize()}
                    className="text-emerald-700 underline hover:text-emerald-900"
                  >
                    Regenerate
                  </button>
                  <button
                    onClick={() => setPlan(null)}
                    className="text-emerald-700 underline hover:text-emerald-900"
                  >
                    Back to chat
                  </button>
                </>
              )}
            </div>
          </section>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[3fr_2fr]">
          {/* Chat panel */}
          <section className="flex flex-col rounded-xl border border-slate-200 bg-white">
            <div className="flex-1 space-y-4 overflow-y-auto p-5" style={{ maxHeight: '60vh' }}>
              {chat.length === 0 && (
                <p className="text-sm text-slate-500">
                  Ask about the customer's situation, or upload a document on the right.
                </p>
              )}
              {chat.map((item, i) => {
                if (item.kind === 'card') {
                  return <ServiceCardView key={i} card={item.card} />
                }
                return (
                  <div key={i} className={item.role === 'user' ? 'text-right' : 'text-left'}>
                    <div
                      className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
                        item.role === 'user'
                          ? 'bg-slate-900 text-white'
                          : 'bg-slate-100 text-slate-900'
                      }`}
                    >
                      {item.content}
                    </div>
                  </div>
                )
              })}
              {streaming && <p className="text-xs text-slate-400">Assistant is responding…</p>}
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); void send() }}
              className="flex gap-2 border-t border-slate-200 p-3"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type a message…"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
                disabled={streaming || planning}
              />
              <button
                type="submit"
                disabled={streaming || planning || !input.trim()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Send
              </button>
            </form>
          </section>

          {/* Documents panel */}
          <section className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="mb-3 text-lg font-medium">Documents</h2>

                <FileDropzone onFiles={(files) => void onFiles(files)} accept={ACCEPT}>
                  Drop files here, or click to browse.
                </FileDropzone>

              <ul className="mt-4 divide-y divide-slate-200">
                {uploads.map((u) => {
                  const processing = u.pct >= 100
                  return (
                    <li key={u.id} className="flex items-start justify-between py-2">
                      <div className="min-w-0 flex-1">
                        <div className="animate-pulse truncate text-sm font-medium text-slate-700">
                          {u.filename}
                        </div>
                        <div className="text-xs text-slate-500">
                          {processing
                            ? 'Uploaded — processing…'
                            : `Uploading · ${u.pct}%`}
                        </div>
                      </div>
                      <div className="ml-2 shrink-0">
                        <Pill
                          tone="busy"
                          label={processing ? 'processing' : 'uploading'}
                        />
                      </div>
                    </li>
                  )
                })}

                {docs.map((d) => {
                  const included = includedIds.has(d.id)
                  let tone: PillTone = 'ok'
                  let label = ''
                  if (d.status === 'ready') {
                    if (included) {
                      label = `ready · ${(d.token_estimate / 1000).toFixed(1)}K tok`
                    } else {
                      tone = 'warn'
                      label = 'ready · skipped (budget)'
                    }
                  } else if (d.status === 'skipped_too_large') {
                    tone = 'warn'
                    label = 'skipped — too large'
                  } else {
                    tone = 'error'
                    label = d.status.replace(/_/g, ' ')
                  }
                  return (
                    <li key={d.id} className="flex items-start justify-between py-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{d.filename}</div>
                        <div className="text-xs text-slate-500">
                          {d.page_count}p · {d.block_count} blocks · {d.route ?? '—'}
                        </div>
                        {d.skip_reason && (
                          <div className="text-xs text-red-600">{d.skip_reason}</div>
                        )}
                      </div>
                      <div className="ml-2 flex shrink-0 flex-col items-end gap-1">
                        <Pill tone={tone} label={label} />
                        <button
                          onClick={() => void removeDoc(d.id)}
                          className="text-[11px] text-slate-400 hover:text-red-600"
                        >
                          remove
                        </button>
                      </div>
                    </li>
                  )
                })}

                {uploads.length === 0 && docs.length === 0 && (
                  <li className="py-4 text-center text-sm text-slate-500">
                    No documents yet.
                  </li>
                )}
              </ul>
            </div>

            {context && (
              <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
                <div className="flex items-baseline justify-between">
                  <span className="font-medium">Context budget</span>
                  <span className="font-mono text-xs text-slate-500">
                    {context.total_tokens.toLocaleString()} / {context.budget_tokens.toLocaleString()} tokens
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full bg-emerald-500"
                    style={{
                      width: `${Math.min(100, (context.total_tokens / context.budget_tokens) * 100)}%`,
                    }}
                  />
                </div>
                <div className="mt-2 text-xs text-slate-500">
                  {context.included.length} document
                  {context.included.length === 1 ? '' : 's'} included
                  {context.skipped.length > 0 && ` · ${context.skipped.length} skipped`}
                </div>
                {context.skipped.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-amber-700">
                    {context.skipped.map((s) => (
                      <li key={s.id}>⚠ {s.filename}: {s.reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}

// ─────────────────────────────────────────────────────────────
// Session expired modal — replaces the whole view. The underlying
// UI is dead anyway, so there's nothing to preserve.
// ─────────────────────────────────────────────────────────────
function SessionExpiredModal() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-lg">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-100">
            <svg
              className="h-5 w-5 text-amber-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-slate-900">Session expired</h2>
            <p className="mt-1 text-sm text-slate-600">
              This session ended after 15 minutes of inactivity. Uploaded
              documents and the chat transcript have been discarded.
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end">
          <Link
            to="/"
            className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Return to Welcome
          </Link>
        </div>
      </div>
    </main>
  )
}

// ─────────────────────────────────────────────────────────────
// Location gate — debounced autocomplete over /api/geocode/search
// ─────────────────────────────────────────────────────────────
function LocationGate({
  session,
  onLocated,
  onCancel,
  onSessionError,
}: {
  session: InterviewSession
  onLocated: (loc: SessionLocation) => void
  /** Provided when re-entering the gate mid-session. */
  onCancel?: () => void
  /** Bubbles up so the parent can show the expired-session modal. */
  onSessionError: () => void
}) {
  const [query, setQuery] = useState(
    session.origin_display_name || session.postal_code || '',
  )
  const [suggestions, setSuggestions] = useState<GeocodeSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [highlighted, setHighlighted] = useState(-1)

  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | null>(null)

  // Abort any in-flight lookup when the gate unmounts.
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  // Debounced lookup; aborts the previous in-flight request.
  useEffect(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    const q = query.trim()
    if (q.length < 2) {
      setSuggestions([])
      setOpen(false)
      setHighlighted(-1)
      return
    }
    timerRef.current = window.setTimeout(async () => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      try {
        const list = await api.geocodeSearch(q, ctrl.signal)
        if (ctrl.signal.aborted) return
        setSuggestions(list)
        setOpen(list.length > 0)
        setHighlighted(list.length > 0 ? 0 : -1)
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          // Silent — the submit path surfaces real geocoder errors.
        }
      }
    }, 300)
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [query])

  async function commit(s: GeocodeSuggestion) {
    setBusy(true)
    setError(null)
    setOpen(false)
    try {
      const loc = await api.interviews.setLocation(session.id, {
        postal_code: s.postcode || query.trim(),
        lat: s.lat,
        lng: s.lng,
        display_name: s.display_name,
        short_display_name: s.short_display_name,
      })
      onLocated(loc)
    } catch (e) {
      if (isSessionError(e)) {
        onSessionError()
        return
      }
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (highlighted >= 0 && suggestions[highlighted]) {
      return void commit(suggestions[highlighted])
    }
    if (suggestions.length > 0) {
      return void commit(suggestions[0])
    }
    // No candidate yet — let the backend geocode + shorten the text.
    setBusy(true)
    setError(null)
    try {
      const loc = await api.interviews.setLocation(session.id, {
        postal_code: query.trim(),
      })
      onLocated(loc)
    } catch (err) {
      if (isSessionError(err)) {
        onSessionError()
        return
      }
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((h) => Math.min(suggestions.length - 1, h + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((h) => Math.max(0, h - 1))
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-md">
        {onCancel ? (
          <button
            onClick={onCancel}
            className="text-sm text-slate-500 hover:text-slate-900"
          >
            ← Cancel
          </button>
        ) : (
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
            ← Back
          </Link>
        )}
        <form
          onSubmit={(e) => void submit(e)}
          className="mt-6 rounded-2xl border border-slate-200 bg-white p-8"
        >
          <h1 className="text-2xl font-semibold text-slate-900">
            Where are you located?
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Start typing a postal code or address — pick a suggestion to continue.
          </p>

          <div className="relative mt-4">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKey}
              onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
              onBlur={() => {
                // Let click handlers fire before closing the list.
                window.setTimeout(() => setOpen(false), 120)
              }}
              placeholder="e.g. M5V 2T6 or 123 Queen St W"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
              disabled={busy}
              autoComplete="off"
            />
            {open && suggestions.length > 0 && (
              <ul className="absolute left-0 right-0 z-10 mt-1 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
                {suggestions.map((s, i) => (
                  <li key={`${s.lat},${s.lng},${i}`}>
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => void commit(s)}
                      onMouseEnter={() => setHighlighted(i)}
                      className={`block w-full px-3 py-2 text-left text-sm ${
                        i === highlighted ? 'bg-slate-100' : 'hover:bg-slate-50'
                      }`}
                    >
                      <div className="font-medium text-slate-900">
                        {s.short_display_name}
                      </div>
                      {s.display_name && s.display_name !== s.short_display_name && (
                        <div className="line-clamp-1 text-xs text-slate-500">
                          {s.display_name}
                        </div>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            type="submit"
            disabled={busy || query.trim().length < 2}
            className="mt-4 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? 'Looking up…' : 'Continue'}
          </button>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </form>
      </div>
    </main>
  )
}


// ─────────────────────────────────────────────────────────────
// Service card rendered inline in the chat flow
// ─────────────────────────────────────────────────────────────
function ServiceCardView({ card }: { card: ServiceCard }) {
  const s = card.service
  const [copied, setCopied] = useState(false)

  async function copyCard() {
    const lines: string[] = [
      `${s.category} — ${s.distance_km.toFixed(1)} km`,
      s.name,
    ]
    const place = [s.location_name, s.address].filter(Boolean).join(' — ')
    if (place) lines.push(place)
    if (s.description) lines.push(s.description)
    if (s.eligibility_description) lines.push(`Eligibility: ${s.eligibility_description}`)
    if (s.application_process) lines.push(`How to apply: ${s.application_process}`)
    if (s.fees_description) lines.push(`Fees: ${s.fees_description}`)
    if (s.email) lines.push(`Email: ${s.email}`)
    if (s.url) lines.push(`URL: ${s.url}`)

    const text = lines.join('\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Fallback for browsers / contexts where the async clipboard API is
      // unavailable (non-HTTPS, older Safari).
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* ignore */ }
      ta.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
            [{String(card.index).padStart(2, '0')}]
          </span>
          <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {s.category}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{s.distance_km.toFixed(1)} km</span>
          <button
            type="button"
            onClick={() => void copyCard()}
            className="rounded-md border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
            aria-live="polite"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
      <h3 className="mt-1 text-base font-semibold text-slate-900">{s.name}</h3>
      {(s.location_name || s.address) && (
        <p className="text-xs text-slate-600">
          {s.location_name}
          {s.location_name && s.address ? ' — ' : ''}
          {s.address}
        </p>
      )}
      {s.description && (
        <p className="mt-2 text-sm text-slate-700">{s.description}</p>
      )}
      {s.eligibility_description && (
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-medium text-slate-700">Eligibility:</span>{' '}
          {s.eligibility_description}
        </p>
      )}
      {s.application_process && (
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-medium text-slate-700">How to apply:</span>{' '}
          {s.application_process}
        </p>
      )}
      {s.fees_description && (
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-medium text-slate-700">Fees:</span>{' '}
          {s.fees_description}
        </p>
      )}
      {(s.email || s.url) && (
        <div className="mt-2 flex flex-wrap gap-3 text-xs">
          {s.email && (
            <a href={`mailto:${s.email}`} className="text-emerald-700 hover:underline">
              {s.email}
            </a>
          )}
          {s.url && (
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-emerald-700 hover:underline"
            >
              {s.url}
            </a>
          )}
        </div>
      )}
    </div>
  )
}