import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const PIN_KEY = 'nav_privacy_pin'
const LOCKED_KEY = 'nav_privacy_locked'

type PrivacyContextValue = {
  locked: boolean
  hasPin: boolean
  lock: () => void
  unlock: (pin: string) => boolean
  setPinAndLock: (pin: string) => void
  clearPin: () => void
}

const PrivacyContext = createContext<PrivacyContextValue | null>(null)

export function PrivacyProvider({ children }: { children: React.ReactNode }) {
  const [pin, setPinState] = useState<string | null>(
    () => sessionStorage.getItem(PIN_KEY),
  )
  // Locked only if a PIN also exists — guards against a stale LOCKED_KEY
  // left behind by some earlier partial state.
  const [locked, setLocked] = useState<boolean>(
    () =>
      sessionStorage.getItem(LOCKED_KEY) === '1' &&
      sessionStorage.getItem(PIN_KEY) !== null,
  )

  useEffect(() => {
    if (locked) sessionStorage.setItem(LOCKED_KEY, '1')
    else sessionStorage.removeItem(LOCKED_KEY)
  }, [locked])

  const lock = useCallback(() => {
    if (!pin) return
    setLocked(true)
  }, [pin])

  const unlock = useCallback(
    (candidate: string) => {
      if (!pin) return false
      if (candidate === pin) {
        setLocked(false)
        return true
      }
      return false
    },
    [pin],
  )

  const setPinAndLock = useCallback((newPin: string) => {
    sessionStorage.setItem(PIN_KEY, newPin)
    setPinState(newPin)
    setLocked(true)
  }, [])

  const clearPin = useCallback(() => {
    sessionStorage.removeItem(PIN_KEY)
    sessionStorage.removeItem(LOCKED_KEY)
    setPinState(null)
    setLocked(false)
  }, [])

  return (
    <PrivacyContext.Provider
      value={{ locked, hasPin: pin !== null, lock, unlock, setPinAndLock, clearPin }}
    >
      {children}
    </PrivacyContext.Provider>
  )
}

export function usePrivacy() {
  const ctx = useContext(PrivacyContext)
  if (!ctx) throw new Error('usePrivacy must be inside PrivacyProvider')
  return ctx
}