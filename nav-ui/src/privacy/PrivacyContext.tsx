import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const LOCKED_KEY = 'nav_privacy_locked'

type PrivacyContextValue = {
  locked: boolean
  lock: () => void
  unlock: () => void
}

const PrivacyContext = createContext<PrivacyContextValue | null>(null)

export function PrivacyProvider({ children }: { children: React.ReactNode }) {
  const [locked, setLocked] = useState<boolean>(
    () => sessionStorage.getItem(LOCKED_KEY) === '1',
  )

  useEffect(() => {
    if (locked) sessionStorage.setItem(LOCKED_KEY, '1')
    else sessionStorage.removeItem(LOCKED_KEY)
  }, [locked])

  const lock = useCallback(() => setLocked(true), [])
  const unlock = useCallback(() => setLocked(false), [])

  return (
    <PrivacyContext.Provider value={{ locked, lock, unlock }}>
      {children}
    </PrivacyContext.Provider>
  )
}

export function usePrivacy() {
  const ctx = useContext(PrivacyContext)
  if (!ctx) throw new Error('usePrivacy must be inside PrivacyProvider')
  return ctx
}