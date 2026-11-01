import type { ReactNode } from 'react'

export type PillTone = 'ok' | 'warn' | 'busy' | 'error' | 'neutral'

const TONE_STYLES: Record<PillTone, { wrap: string; dot: string }> = {
  ok:      { wrap: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
  warn:    { wrap: 'bg-amber-50 text-amber-700',     dot: 'bg-amber-500' },
  busy:    { wrap: 'bg-amber-50 text-amber-700',     dot: 'bg-amber-500 animate-pulse' },
  error:   { wrap: 'bg-red-50 text-red-700',         dot: 'bg-red-500' },
  neutral: { wrap: 'bg-slate-100 text-slate-500',    dot: 'bg-slate-400' },
}

export function Pill({
  tone,
  label,
  detail,
}: {
  tone: PillTone
  label: string
  detail?: ReactNode
}) {
  const s = TONE_STYLES[tone]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs ${s.wrap}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      <span className="font-medium">{label}</span>
      {detail && <span className="font-mono opacity-60">{detail}</span>}
    </span>
  )
}