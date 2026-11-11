import { LANGUAGES, PROMOTED_LOCALES } from '../languages'
import { useT } from '../i18n/I18nContext'

/**
 * Full-screen language picker for the kiosk welcome step.
 *
 * Why a flat grid and not a search box: kiosk users are often in
 * distress and unfamiliar with the venue's UI. A visual cloud of
 * native-script names is faster to scan than a text field, and the
 * promoted locales (fr/es/zh/pa — the local population) are pushed
 * to the top so the majority pick in one tap.
 *
 * Every tile shows the native name large and the English name small.
 * The English name serves kiosk staff and anyone searching visually
 * for a language they recognise phonetically but can't read natively.
 */
export function LanguageCloud({
  current,
  onPick,
}: {
  current: string
  onPick: (code: string) => void
}) {
  const { t } = useT()

  const promoted = PROMOTED_LOCALES
    .map((code) => LANGUAGES.find((l) => l.code === code))
    .filter((l): l is (typeof LANGUAGES)[number] => l !== undefined)

  const others = LANGUAGES
    .filter((l) => !PROMOTED_LOCALES.includes(l.code as never))
    .slice()
    .sort((a, b) => a.english.localeCompare(b.english))

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="mx-auto max-w-5xl">
        <header className="mb-6 text-center">
          <h1 className="text-3xl font-semibold text-slate-900">
            {t('welcome.choose_language')}
          </h1>
        </header>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
            {promoted.map((l) => (
              <Tile
                key={l.code}
                code={l.code}
                native={l.native}
                english={l.english}
                selected={current === l.code}
                onClick={() => onPick(l.code)}
              />
            ))}
          </div>

          <div className="my-4 border-t border-slate-200" />

          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
              {others.map((l) => (
                <Tile
                  key={l.code}
                  code={l.code}
                  native={l.native}
                  english={l.english}
                  selected={current === l.code}
                  onClick={() => onPick(l.code)}
                  compact
                />
              ))}
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}

function Tile({
  native,
  english,
  selected,
  onClick,
  compact = false,
}: {
  code: string
  native: string
  english: string
  selected: boolean
  onClick: () => void
  compact?: boolean
}) {
  const base =
    'flex flex-col items-center justify-center rounded-xl border-2 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400'
  const active = 'border-slate-900 bg-slate-900 text-white'
  const idle = 'border-slate-200 bg-white text-slate-900 hover:border-slate-400'
  const size = compact ? 'min-h-[64px] px-2 py-2' : 'min-h-[88px] px-3 py-3'
  return (
    <button
      onClick={onClick}
      className={`${base} ${selected ? active : idle} ${size}`}
    >
      <span className={compact ? 'text-sm font-medium' : 'text-base font-medium'}>
        {native}
      </span>
      <span
        className={`mt-0.5 ${
          compact ? 'text-[10px]' : 'text-xs'
        } ${selected ? 'text-slate-300' : 'text-slate-500'}`}
      >
        {english}
      </span>
    </button>
  )
}