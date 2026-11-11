import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { api } from '../api'
import { LANGUAGES } from '../languages'
import { ENGLISH_STRINGS } from './english'

// Locales whose script direction is RTL. The set is small and stable;
// adding a locale means adding its ISO code here (and it must also
// appear in src/languages.ts to be pickable).
const RTL_LOCALES = new Set([
  'ar', 'he', 'fa', 'ur', 'ps', 'ug', 'dv', 'yi',
])

const STORAGE_KEY = 'nav_locale'

type I18nValue = {
  locale: string
  localeName: string          // English name, e.g. "French"
  setLocale: (l: string) => void
  t: (key: string, vars?: Record<string, string | number>) => string
  rtl: boolean
  loaded: boolean
}

const I18nContext = createContext<I18nValue | null>(null)

function format(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (_, k: string) =>
    Object.prototype.hasOwnProperty.call(vars, k)
      ? String(vars[k])
      : `{${k}}`,
  )
}

function initialLocale(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return stored
  } catch {
    /* private mode / disabled storage — fall through */
  }
  return 'en'
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<string>(initialLocale)
  const [translations, setTranslations] = useState<Record<string, string>>({})
  const [loaded, setLoaded] = useState(false)

  // Persist on change. Kiosk restart preserves the last-used language;
  // the Welcome language picker is still shown at the start of every
  // session (see Welcome.tsx) so this is just a convenience default.
  const setLocale = useCallback((l: string) => {
    setLocaleState(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
  }, [])

  // Fetch translations whenever the locale changes. English short-
  // circuits: the bundle is the dictionary.
  useEffect(() => {
    let alive = true
    setTranslations({})
    if (locale === 'en') {
      setLoaded(true)
      return () => { alive = false }
    }
    setLoaded(false)
    api.ui.strings(locale)
      .then((r) => {
        if (!alive) return
        setTranslations(r.strings)
        setLoaded(true)
      })
      .catch(() => {
        if (!alive) return
        // Fall through to English fallback via t() — log quietly.
        setTranslations({})
        setLoaded(true)
      })
    return () => { alive = false }
  }, [locale])

  // Flip <html> lang/dir so Tailwind's logical properties and any
  // browser-native controls (input direction, scrollbars) follow.
  useEffect(() => {
    document.documentElement.lang = locale
    document.documentElement.dir = RTL_LOCALES.has(locale) ? 'rtl' : 'ltr'
  }, [locale])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      const template =
        translations[key] ??
        ENGLISH_STRINGS[key] ??
        key
      return format(template, vars)
    },
    [translations],
  )

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      localeName:
        LANGUAGES.find((l) => l.code === locale)?.english ?? locale,
      setLocale,
      t,
      rtl: RTL_LOCALES.has(locale),
      loaded,
    }),
    [locale, setLocale, t, loaded],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useT() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useT must be inside I18nProvider')
  return ctx
}