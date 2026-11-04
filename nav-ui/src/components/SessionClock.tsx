import { useEffect, useRef, useState } from 'react'
import { Pill, type PillTone } from './Pill'
import { onRequest } from '../api'

const IDLE_MS = 15 * 60_000   // must match NAVIGATOR_SESSION_IDLE_MINUTES

export function SessionClock({
  seedExpiresAt,
  onExpired,
}: {
  seedExpiresAt: string | null
  onExpired: () => void
}) {
  const [lastAt, setLastAt] = useState<number>(() => {
    if (seedExpiresAt) {
      const t = new Date(seedExpiresAt).getTime()
      if (!Number.isNaN(t)) return t - IDLE_MS
    }
    return Date.now()
  })
  const [now, setNow] = useState(Date.now())
  const firedRef = useRef(false)
  const onExpiredRef = useRef(onExpired)

  useEffect(() => {
    onExpiredRef.current = onExpired
  }, [onExpired])

  // Every request slides the window locally.
  useEffect(() => {
    return onRequest((t) => {
      setLastAt(t)
      firedRef.current = false
    })
  }, [])

  // Seed (or reseed on new session).
  useEffect(() => {
    if (!seedExpiresAt) return
    const t = new Date(seedExpiresAt).getTime()
    if (Number.isNaN(t)) return
    setLastAt(t - IDLE_MS)
    firedRef.current = false
  }, [seedExpiresAt])

  // 1-second tick.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const remaining = lastAt + IDLE_MS - now
  const expired = remaining <= 0

  // Verify exactly once per "expired" episode.
  useEffect(() => {
    if (!expired || firedRef.current) return
    firedRef.current = true
    onExpiredRef.current()
  }, [expired])

  // Don't flash a value before the session arrives.
  if (!seedExpiresAt) return null

  if (expired) {
    return <Pill tone="error" label="session ending" />
  }

  // Floor to whole minutes. Thresholds read naturally off the label:
  // "6m" green, "5m".."3m" yellow, "2m" red.
  const mins = Math.floor(remaining / 60_000)
  const tone: PillTone =
    mins >= 6 ? 'ok' : mins >= 3 ? 'warn' : 'error'
  const detail = mins < 1 ? '<1m' : `${mins}m`

  return <Pill tone={tone} label="session" detail={detail} />
}