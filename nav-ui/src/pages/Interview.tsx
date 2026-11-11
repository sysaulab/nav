// nav-ui/src/pages/Interview.tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as React from 'react'
import { api, isSessionError } from '../api'
import { Pill, type PillTone } from '../components/Pill'
import FileDropzone from '../components/FileDropzone'
import { AddressAutocomplete } from '../components/AddressAutocomplete'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { matchesAccept } from '../util/files.tsx'
import { usePrivacy } from '../privacy/PrivacyContext'
import { SessionClock } from '../components/SessionClock'
import { useT } from '../i18n/I18nContext'
import type {
  ChatItem, ChatMessage, ContextPrompt, DocumentMeta, GeocodeSuggestion,
  InterviewSession, ServiceCard, SessionLocation,
} from '../types'

type Upload = { id: string; filename: string; pct: number }

export default function Interview() {
  const navigate = useNavigate()
  const { unlock } = usePrivacy()
  const { locale, localeName, t } = useT()
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
  const planHtmlRef = useRef<HTMLElement>(null)

  const [editingLocation, setEditingLocation] = useState(false)
  const [confirmEndOpen, setConfirmEndOpen] = useState(false)

  const handleApiError = useCallback((e: unknown): boolean => {
    if (isSessionError(e)) {
      setSessionExpired(true)
      return true
    }
    setError((e as Error).message)
    return false
  }, [])

  const refresh = useCallback(async (sid: string, messages: ChatMessage[] = []) => {
    try {
      const [d, c] = await Promise.all([
        api.interviews.documents.list(sid),
        api.interviews.contextPrompt(sid, messages),
      ])
      setDocs(d)
      setContext(c)
    } catch (e) {
      handleApiError(e)
    }
  }, [handleApiError])

  useEffect(() => {
    let live = true

    async function init() {
      try {
        console.log('[init] starting')
        const s = await api.interviews.createOrResume()
        console.log('[init] session:', s.id, 'postal_code:', s.postal_code)
        if (!live) return

        let finalSession = s
        const pendingRaw = sessionStorage.getItem('pending_location')
        console.log('[init] pending_location present:', !!pendingRaw)

        if (pendingRaw) {
          sessionStorage.removeItem('pending_location')
          try {
            const pending = JSON.parse(pendingRaw) as GeocodeSuggestion
            console.log('[init] applying pending location:', pending.display_name)
            const loc = await api.interviews.setLocation(s.id, {
              postal_code: pending.postcode || pending.city || 'Unknown',
              lat: pending.lat,
              lng: pending.lng,
              display_name: pending.display_name,
            })
            console.log('[init] location resolved:', loc.postal_code)
            if (!live) return
            finalSession = {
              ...s,
              postal_code: loc.postal_code,
              origin_display_name: loc.origin_display_name,
            }
          } catch (e) {
            console.error('[init] setLocation failed:', e)
          }
        }

        if (!live) return
        console.log('[init] setting session, final postal_code:', finalSession.postal_code)
        setSession(finalSession)

        if (!finalSession.postal_code) {
          console.log('[init] no location, navigating to welcome')
          navigate('/', { replace: true })
        }
      } catch (e) {
        console.error('[init] fatal:', e)
        if (live) setError((e as Error).message || 'Failed to start session')
      }
    }

    void init()
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (!session || streaming) return
    const messages = chat
      .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
      .map((i) => ({ role: i.role, content: i.content }))
    api.interviews.contextPrompt(session.id, messages)
      .then(setContext)
      .catch(() => {})
  }, [chat, session, streaming])

  const ACCEPT =
    '.rtf,.pdf,.txt,.md,.docx,.odt,.ods,.odp,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,.xlsx,.pptx'

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
      ? t('documents.error_legacy_office', {
          filename,
          ext,
          replacement,
        })
      : null
  }

  async function verifyExpired() {
    if (!session) return
    try {
      await api.interviews.location(session.id)
    } catch (e) {
      if (isSessionError(e)) setSessionExpired(true)
    }
  }

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
            : t('documents.error_unsupported_type'),
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
            : t('documents.error_skipped_count', { n: rejectedFiles.length }),
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
          const msgs = chat
            .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
            .map((i) => ({ role: i.role, content: i.content }))
          await refresh(session.id, msgs)
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
      const msgs = chat
        .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
        .map((i) => ({ role: i.role, content: i.content }))
      await refresh(session.id, msgs)
    } catch (e) {
      handleApiError(e)
    }
  }

  // The click on "End session" only opens the modal. The modal's
  // confirm button calls doEndSession, which does the actual work.
  // Splitting the two means the modal's open/close is pure UI state,
  // and the async side effects never run unless the user confirms.
  function endSession() {
    if (!session) return
    setConfirmEndOpen(true)
  }

  async function doEndSession() {
    setConfirmEndOpen(false)
    if (!session) return
    try {
      await api.interviews.end(session.id)
      unlock()
      setSession(null)
      setDocs([])
      setContext(null)
      setChat([])
      setPlan(null)
      navigate('/')
    } catch (e) {
      if (isSessionError(e)) {
        navigate('/')
      } else {
        setError((e as Error).message)
      }
    }
  }

  async function send() {
    if (!session || !input.trim() || streaming) return
    const userMsg: ChatMessage = { role: 'user', content: input.trim() }

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
      assistantBuf = ''
      setChat((prev) => [...prev, { kind: 'card', card }])
    }

    try {
      await api.interviews.chat(session.id, apiMessages, locale, localeName, (raw) => {
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
      await api.interviews.finalize(session.id, priorMessages, locale, localeName, (raw) => {
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

  function getPlanHtml(): string {
    return planHtmlRef.current?.innerHTML ?? ''
  }

  async function copyPlan() {
    if (plan === null || !plan) return
    const html = getPlanHtml()
    if (!html) {
      setError('Plan is still rendering; try again in a moment.')
      return
    }

    try {
      if (typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
        await navigator.clipboard.write([
          new ClipboardItem({
            'text/html': new Blob([html], { type: 'text/html' }),
            'text/plain': new Blob([plan], { type: 'text/plain' }),
          }),
        ])
      } else {
        await navigator.clipboard.writeText(plan)
      }
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
    const html = getPlanHtml()
    if (!html) {
      setError('Plan is still rendering; try again in a moment.')
      return
    }

    setExportingDocx(true)
    setError(null)
    const stem = `action-plan-${session?.id.slice(0, 8) ?? 'session'}`
    try {
      const res = await fetch('/api/export/docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html, filename: stem }),
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

  if (sessionExpired) {
    return <SessionExpiredModal />
  }

  if (!session) {
    return (
      <main className="min-h-screen bg-slate-50 p-8">
        <div className="mx-auto max-w-3xl">
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
            {t('location.back')}
          </Link>
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-8 text-center">
            <p className="text-slate-600">{t('interview.starting_session')}</p>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </div>
        </div>
      </main>
    )
  }

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
          setPlan(null)
          const msgs = chat
            .filter((i): i is Extract<ChatItem, { kind: 'message' }> => i.kind === 'message')
            .map((i) => ({ role: i.role, content: i.content }))
          void refresh(session.id, msgs)
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
              {t('interview.change_location')}
            </button>
            <span className="text-xs text-slate-400">|</span>
            <span className="text-xs text-slate-500">
              {t('interview.location_label')}{' '}
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
                {planning ? t('interview.finishing') : t('interview.finish')}
              </button>
            )}
            <button
              onClick={endSession}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              {t('interview.end_session')}
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
                <h2 className="text-lg font-medium text-emerald-900">
                  {t('plan.title')}
                </h2>
                {planning && (
                  <span className="text-xs text-emerald-700">
                    {t('plan.generating')}
                  </span>
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
                    {copied ? t('plan.copied') : t('plan.copy')}
                  </button>
                  <button
                    type="button"
                    onClick={downloadPlan}
                    className="rounded-lg border border-emerald-400 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
                  >
                    {t('plan.download_markdown')}
                  </button>
                  <button
                    type="button"
                    onClick={() => void downloadDocx()}
                    disabled={exportingDocx}
                    className="rounded-lg border border-emerald-400 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
                  >
                    {exportingDocx
                      ? t('plan.download_office_working')
                      : t('plan.download_office')}
                  </button>
                </div>
              )}
            </div>

            {plan ? (
              <article
                ref={planHtmlRef}
                className="prose prose-sm prose-slate mt-3 max-w-none prose-headings:font-semibold prose-headings:text-slate-900 prose-a:text-emerald-700 prose-code:text-emerald-800 prose-pre:bg-slate-900"
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{plan}</ReactMarkdown>
              </article>
            ) : (
              !planning && (
                <p className="mt-3 text-sm text-emerald-950">
                  {t('plan.no_content')}
                </p>
              )
            )}

            <div className="mt-3 flex justify-end gap-3 text-xs">
              {!planning && (
                <>
                  <button
                    onClick={() => void finalize()}
                    className="text-emerald-700 underline hover:text-emerald-900"
                  >
                    {t('plan.regenerate')}
                  </button>
                  <button
                    onClick={() => setPlan(null)}
                    className="text-emerald-700 underline hover:text-emerald-900"
                  >
                    {t('plan.back_to_chat')}
                  </button>
                </>
              )}
            </div>
          </section>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[3fr_2fr]">
          <section className="flex flex-col rounded-xl border border-slate-200 bg-white">
            <div className="flex-1 space-y-4 overflow-y-auto p-5" style={{ maxHeight: '60vh' }}>
              {chat.length === 0 && (
                <p className="text-sm text-slate-500">{t('chat.empty_prompt')}</p>
              )}
              {chat.map((item, i) => {
                if (item.kind === 'card') {
                  return <ServiceCardView key={i} card={item.card} />
                }
                const isUser = item.role === 'user'
                return (
                  <div key={i} className={isUser ? 'text-right' : 'text-left'}>
                    <div
                      className={`inline-block max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                        isUser
                          ? 'bg-slate-900 text-white whitespace-pre-wrap'
                          : 'bg-slate-100 text-slate-900'
                      }`}
                    >
                      {isUser ? (
                        item.content
                      ) : (
                        <div className="prose prose-sm prose-slate max-w-none prose-p:leading-relaxed prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-a:text-emerald-700">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {item.content}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              {streaming && (
                <p className="text-xs text-slate-400">
                  {t('chat.assistant_responding')}
                </p>
              )}
            </div>
            <form
              onSubmit={(e) => { e.preventDefault(); void send() }}
              className="flex gap-2 border-t border-slate-200 p-3"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t('chat.type_message')}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
                disabled={streaming || planning}
              />
              <button
                type="submit"
                disabled={streaming || planning || !input.trim()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {t('chat.send')}
              </button>
            </form>
          </section>

          <section className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="mb-3 text-lg font-medium">{t('documents.title')}</h2>

              <FileDropzone onFiles={(files) => void onFiles(files)} accept={ACCEPT}>
                {t('documents.dropzone')}
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
                            ? t('documents.processing')
                            : t('documents.uploading', { pct: u.pct })}
                        </div>
                      </div>
                      <div className="ml-2 shrink-0">
                        <Pill
                          tone="busy"
                          label={
                            processing
                              ? t('documents.status_processing')
                              : t('documents.status_uploading')
                          }
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
                      label = t('documents.status_ready', {
                        k: (d.token_estimate / 1000).toFixed(1),
                      })
                    } else {
                      tone = 'warn'
                      label = t('documents.status_ready_skipped')
                    }
                  } else if (d.status === 'skipped_too_large') {
                    tone = 'warn'
                    label = t('documents.status_skipped_too_large')
                  } else {
                    tone = 'error'
                    label = t(`documents.status_${d.status}`)
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
                          {t('documents.remove')}
                        </button>
                      </div>
                    </li>
                  )
                })}

                {uploads.length === 0 && docs.length === 0 && (
                  <li className="py-4 text-center text-sm text-slate-500">
                    {t('documents.empty')}
                  </li>
                )}
              </ul>
            </div>

            {context && (() => {
              const totalTokens = context.total_tokens ?? 0
              const contextWindow = context.context_window ?? context.budget_tokens ?? 0
              const budgetTokens = context.budget_tokens ?? contextWindow
              const outputReserve = context.output_reserve_tokens ?? (contextWindow - budgetTokens)
              const included = context.included ?? []
              const skipped = context.skipped ?? []

              return (
                <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
                  <div className="flex items-baseline justify-between">
                    <span className="font-medium">{t('context.title')}</span>
                    <span className="font-mono text-xs text-slate-500">
                      {t('context.tokens_composed', {
                        used: totalTokens.toLocaleString(),
                        total: contextWindow.toLocaleString(),
                      })}
                    </span>
                  </div>
                  {contextWindow > 0 && (
                    <div className="mt-2 relative h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className={`h-full ${totalTokens > budgetTokens ? 'bg-red-500' : 'bg-emerald-500'}`}
                        style={{
                          width: `${Math.min(100, (totalTokens / contextWindow) * 100)}%`,
                        }}
                      />
                      <div
                        className="absolute top-0 bottom-0 w-0.5 bg-slate-900 opacity-50"
                        style={{
                          left: `${(budgetTokens / contextWindow) * 100}%`,
                        }}
                      />
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                    <span>
                      {t('context.docs_included', {
                        n: included.length,
                        s: included.length === 1 ? '' : 's',
                      })}
                      {skipped.length > 0 && (
                        <>
                          {' · '}
                          {t('context.docs_skipped_suffix', { n: skipped.length })}
                        </>
                      )}
                    </span>
                    <span>
                      {t('context.reserved_for_reply', {
                        n: outputReserve.toLocaleString(),
                      })}
                    </span>
                  </div>
                  {skipped.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs text-amber-700">
                      {skipped.map((s) => (
                        <li key={s.id}>⚠ {s.filename}: {s.reason}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })()}
          </section>
        </div>
      </div>

      <ConfirmDialog
        open={confirmEndOpen}
        title={t('interview.end_session')}
        body={t('confirm.end_session')}
        confirmLabel={t('confirm.end_session_yes')}
        cancelLabel={t('confirm.cancel')}
        onConfirm={() => void doEndSession()}
        onCancel={() => setConfirmEndOpen(false)}
      />
    </main>
  )
}

function SessionExpiredModal() {
  const { t } = useT()
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
            <h2 className="text-lg font-semibold text-slate-900">
              {t('session.expired_title')}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {t('session.expired_body')}
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end">
          <Link
            to="/"
            className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            {t('session.expired_return')}
          </Link>
        </div>
      </div>
    </main>
  )
}

function LocationGate({
  session,
  onLocated,
  onCancel,
  onSessionError,
}: {
  session: InterviewSession
  onLocated: (loc: SessionLocation) => void
  onCancel?: () => void
  onSessionError: () => void
}) {
  const { t } = useT()
  const [query, setQuery] = useState(
    session.origin_display_name || session.postal_code || '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSelect(s: GeocodeSuggestion) {
    setBusy(true)
    setError(null)
    try {
      const loc = await api.interviews.setLocation(session.id, {
        postal_code: s.postcode || s.city || query.trim(),
        lat: s.lat,
        lng: s.lng,
        display_name: s.display_name,
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

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <div className="w-full max-w-md">
        {onCancel ? (
          <button
            onClick={onCancel}
            className="text-sm text-slate-500 hover:text-slate-900"
          >
            {t('location.cancel')}
          </button>
        ) : (
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
            {t('location.back')}
          </Link>
        )}
        <form
          onSubmit={(e) => void submit(e)}
          className="mt-6 rounded-2xl border border-slate-200 bg-white p-8"
        >
          <h1 className="text-2xl font-semibold text-slate-900">
            {t('location.title')}
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            {t('location.subtitle')}
          </p>

          <div className="mt-4">
            <AddressAutocomplete
              value={query}
              onChange={setQuery}
              onSelect={(s) => void onSelect(s)}
              placeholder={t('welcome.address_placeholder')}
              disabled={busy}
              autoFocus
            />
          </div>

          <button
            type="submit"
            disabled={busy || query.trim().length < 2}
            className="mt-4 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? t('location.looking_up') : t('location.continue')}
          </button>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </form>
      </div>
    </main>
  )
}

function ServiceCardView({ card }: { card: ServiceCard }) {
  const { t } = useT()
  const s = card.service
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const distLabel =
    s.distance_km !== null
      ? t('card.distance_km', { d: s.distance_km.toFixed(1) })
      : t('card.global')

  const categoryLabel = t(`category.${s.category}`)

  // Hover tooltip on the truncated location name so the full place —
  // name and address — is still discoverable without expanding.
  const tooltip =
    [s.location_name, s.address].filter(Boolean).join(' — ') || undefined

  async function copyCard() {
    const distStr =
      s.distance_km !== null
        ? t('card.distance_km', { d: s.distance_km.toFixed(1) })
        : t('card.global')
    const lines: string[] = [`${categoryLabel} — ${distStr}`, s.name]
    const placeStr = [s.location_name, s.address].filter(Boolean).join(' — ')
    if (placeStr) lines.push(placeStr)
    if (s.description) lines.push(s.description)
    if (s.eligibility_description)
      lines.push(`${t('card.eligibility')} ${s.eligibility_description}`)
    if (s.application_process)
      lines.push(`${t('card.application')} ${s.application_process}`)
    if (s.fees_description)
      lines.push(`${t('card.fees')} ${s.fees_description}`)
    if (s.email) lines.push(`${t('card.email')} ${s.email}`)
    if (s.url) lines.push(`${t('card.url')} ${s.url}`)

    const text = lines.join('\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
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
    <div className="min-w-0 max-w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* One-line header. Every fixed element is shrink-0, so only the
          location name can absorb width — and it truncates with an
          ellipsis the moment the container narrows below its natural
          width. min-w-0 + overflow-hidden at every flex boundary is
          what actually allows `truncate` to fire inside a flex context. */}
      <div className="flex min-w-0 max-w-full items-center gap-2 overflow-hidden px-3 py-2 text-sm">
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="shrink-0 rounded px-1 font-mono text-[11px] leading-none text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          aria-label={expanded ? t('card.collapse') : t('card.expand')}
          aria-expanded={expanded}
        >
          {expanded ? '[-]' : '[+]'}
        </button>
        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
          {categoryLabel}
        </span>
        <span className="shrink-0 text-xs text-slate-500">{distLabel}</span>
        {s.location_name && (
          <>
            <span className="shrink-0 text-slate-400">—</span>
            <span
              className="min-w-0 flex-1 truncate text-sm text-slate-700"
              title={tooltip}
            >
              {s.location_name}
            </span>
          </>
        )}
        {!s.location_name && <span className="min-w-0 flex-1" />}
        <button
          type="button"
          onClick={() => void copyCard()}
          className="shrink-0 rounded-md border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
          aria-live="polite"
        >
          {copied ? t('plan.copied') : t('plan.copy')}
        </button>
      </div>

      {expanded && (
        <div className="space-y-2 border-t border-slate-200 px-4 py-3">
          <h3 className="text-base font-semibold text-slate-900">{s.name}</h3>
          {(s.location_name || s.address) && (
            <p className="text-xs text-slate-600">
              {s.location_name}
              {s.location_name && s.address ? ' — ' : ''}
              {s.address}
            </p>
          )}
          {s.description && (
            <p className="text-sm text-slate-700">{s.description}</p>
          )}
          {s.eligibility_description && (
            <p className="text-xs text-slate-600">
              <span className="font-medium text-slate-700">
                {t('card.eligibility')}
              </span>{' '}
              {s.eligibility_description}
            </p>
          )}
          {s.application_process && (
            <p className="text-xs text-slate-600">
              <span className="font-medium text-slate-700">
                {t('card.application')}
              </span>{' '}
              {s.application_process}
            </p>
          )}
          {s.fees_description && (
            <p className="text-xs text-slate-600">
              <span className="font-medium text-slate-700">
                {t('card.fees')}
              </span>{' '}
              {s.fees_description}
            </p>
          )}
          {(s.email || s.url) && (
            <div className="flex flex-wrap gap-3 pt-1 text-xs">
              {s.email && (
                <a
                  href={`mailto:${s.email}`}
                  className="text-emerald-700 hover:underline"
                >
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
      )}
    </div>
  )
}