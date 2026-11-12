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
  // Gate the very first render. Before the first fetch resolves,
  // `translations` is empty and `t()` would emit raw keys
  // ("welcome.title") for a frame. Return an inert shell instead.
  // Subsequent locale switches do NOT re-trigger this gate — the
  // previous locale's strings stay visible until the new ones land.
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false)

  // Persist on change. Kiosk restart preserves the last-used language;
  // the Welcome language picker is still shown at the start of every
  // session (see Welcome.tsx) so this is just a convenience default.
  const setLocale = useCallback((l: string) => {
    setLocaleState(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
  }, [])

  // Fetch translations whenever the locale changes. Every locale —
  // including English — is served by the backend from
  // ui_string_translation. There is no client-side dictionary and no
  // English short-circuit: a language is a language. English is
  // seeded from ui_strings.py on the server (translator signature
  // "source") and can be overridden via the admin UI (signature
  // "manual"), and the client sees whichever one the server serves.
  useEffect(() => {
    let alive = true
    // Deliberately do NOT clear `translations` here. On a locale switch
    // this keeps the previous language's text visible for the ~100 ms
    // the fetch takes, instead of flashing raw keys. `loaded` still
    // flips to false so any consumer that wants a "translating…" cue
    // can show one.
    setLoaded(false)
    api.ui.strings(locale)
      .then((r) => {
        if (!alive) return
        setTranslations(r.strings)
        setLoaded(true)
        setHasLoadedOnce(true)
      })
      .catch(() => {
        if (!alive) return
        // Fail-open: drop to raw keys. On the very first load this is
        // the initial {} state anyway; on a switch failure this is
        // explicit — better than showing the previous locale's text
        // under a new language code. The kiosk is talking to its own
        // backend; if this fails, sessions/chat fail too.
        setTranslations({})
        setLoaded(true)
        setHasLoadedOnce(true)
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
      // Missing key falls through to the raw key. There is no bundled
      // fallback dictionary — English comes from the server like every
      // other locale. A visible "welcome.title" on screen means the
      // backend is unreachable, which is the honest signal.
      const template = translations[key] ?? key
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

  if (!hasLoadedOnce) {
    return <div className="min-h-screen bg-slate-50" />
  }

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useT() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useT must be inside I18nProvider')
  return ctx
}