import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { api, ApiError, setToken } from './api'

type AuthValue = {
  authed: boolean
  loading: boolean
  submitToken: (token: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    const stored = sessionStorage.getItem('nav_admin_token')
    if (!stored) {
      setLoading(false)
      return
    }
    api.health()
      .then(() => {
        if (live) {
          setAuthed(true)
          setLoading(false)
        }
      })
      .catch(() => {
        if (live) {
          setToken(null)
          setAuthed(false)
          setLoading(false)
        }
      })
    return () => {
      live = false
    }
  }, [])

  const submitToken = useCallback(async (token: string) => {
    setToken(token)
    try {
      await api.health()
      setAuthed(true)
    } catch (e) {
      setToken(null)
      if (e instanceof ApiError) throw e
      throw new Error((e as Error).message)
    }
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setAuthed(false)
  }, [])

  return (
    <AuthContext.Provider value={{ authed, loading, submitToken, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}