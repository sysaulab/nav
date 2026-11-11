import { useEffect, useRef, useState } from 'react'
import { Pill, type PillTone } from './Pill'
import { onRequest } from '../api'
import { useT } from '../i18n/I18nContext'

const IDLE_MS = 15 * 60_000

export function SessionClock({
  seedExpiresAt,
  onExpired,
}: {
  seedExpiresAt: string | null
  onExpired: () => void
}) {
  const { t } = useT()
  const [lastAt, setLastAt] = useState<number>(() => {
    if (seedExpiresAt) {
      const t0 = new Date(seedExpiresAt).getTime()
      if (!Number.isNaN(t0)) return t0 - IDLE_MS
    }
    return Date.now()
  })
  const [now, setNow] = useState(Date.now())
  const firedRef = useRef(false)
  const onExpiredRef = useRef(onExpired)

  useEffect(() => { onExpiredRef.current = onExpired }, [onExpired])

  useEffect(() => onRequest((t0) => { setLastAt(t0); firedRef.current = false }), [])

  useEffect(() => {
    if (!seedExpiresAt) return
    const t0 = new Date(seedExpiresAt).getTime()
    if (Number.isNaN(t0)) return
    setLastAt(t0 - IDLE_MS)
    firedRef.current = false
  }, [seedExpiresAt])

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const remaining = lastAt + IDLE_MS - now
  const expired = remaining <= 0

  useEffect(() => {
    if (!expired || firedRef.current) return
    firedRef.current = true
    onExpiredRef.current()
  }, [expired])

  if (!seedExpiresAt) return null

  if (expired) {
    return <Pill tone="error" label={t('clock.session_ending')} />
  }

  const mins = Math.floor(remaining / 60_000)
  const tone: PillTone = mins >= 6 ? 'ok' : mins >= 3 ? 'warn' : 'error'
  const detail =
    mins < 1 ? t('clock.less_than_minute') : t('clock.minutes_left', { n: mins })

  return <Pill tone={tone} label={t('clock.session')} detail={detail} />
}