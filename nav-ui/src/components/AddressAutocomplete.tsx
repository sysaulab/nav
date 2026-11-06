import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { GeocodeSuggestion } from '../types'

type Props = {
  value: string
  onChange: (value: string) => void
  onSelect: (suggestion: GeocodeSuggestion) => void
  placeholder?: string
  disabled?: boolean
  autoFocus?: boolean
  /**
   * When false, the input is still editable but no Photon lookup runs and
   * the dropdown never opens. Used by "Freeze coordinates — edit address
   * manually" mode: the user is deliberately typing an address that Photon
   * won't match (e.g. an odd number missing from OSM), so querying it
   * would only produce noise.
   */
  suggestionsEnabled?: boolean
  onLookupError?: (err: Error) => void
}

/**
 * Debounced address autocomplete over /api/geocode/search.
 *
 * Controlled component: the parent owns `value` and receives every edit via
 * `onChange`. When the user picks a suggestion the parent gets `onSelect`;
 * the subsequent `value` change is not re-queried (see skipNextLookupRef),
 * so the dropdown doesn't reopen over the resolved label.
 */
export function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  placeholder,
  disabled,
  autoFocus,
  suggestionsEnabled = true,
  onLookupError,
}: Props) {
  const [suggestions, setSuggestions] = useState<GeocodeSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)

  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | null>(null)
  // Set to true immediately before the parent updates `value` from a
  // selection. The effect that fires on that change reads it, resets it,
  // and skips the lookup — otherwise picking a suggestion would immediately
  // re-query Photon with the resolved label and reopen the dropdown.
  const skipNextLookupRef = useRef(false)

  useEffect(() => {
    if (!suggestionsEnabled) {
      // Cancel any in-flight lookup and clear the dropdown. Typing
      // continues to update `value` via the parent; nothing else happens.
      abortRef.current?.abort()
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      setSuggestions([])
      setOpen(false)
      setHighlighted(-1)
      return
    }

    if (skipNextLookupRef.current) {
      skipNextLookupRef.current = false
      setSuggestions([])
      setOpen(false)
      setHighlighted(-1)
      return
    }

    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    const q = value.trim()
    if (q.length < 2) {
      setSuggestions([])
      setOpen(false)
      setHighlighted(-1)
      return
    }
    timerRef.current = window.setTimeout(async () => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      try {
        const list = await api.geocodeSearch(q, ctrl.signal)
        if (ctrl.signal.aborted) return
        setSuggestions(list)
        setOpen(list.length > 0)
        setHighlighted(list.length > 0 ? 0 : -1)
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          onLookupError?.(e as Error)
        }
      }
    }, 300)
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [value, onLookupError, suggestionsEnabled])

  function choose(s: GeocodeSuggestion) {
    skipNextLookupRef.current = true
    setOpen(false)
    setSuggestions([])
    setHighlighted(-1)
    onSelect(s)
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((h) => Math.min(suggestions.length - 1, h + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((h) => Math.max(0, h - 1))
    } else if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'Enter' && open && highlighted >= 0) {
      // Only intercept Enter when a suggestion is highlighted; otherwise
      // let the enclosing form's submit handler fire normally.
      e.preventDefault()
      choose(suggestions[highlighted])
    }
  }

  return (
    <div className="relative">
      <input
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
        onBlur={() => {
          // Delay so click handlers on the dropdown fire before it closes.
          window.setTimeout(() => setOpen(false), 120)
        }}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        disabled={disabled}
        autoComplete="off"
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute left-0 right-0 z-10 mt-1 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          {suggestions.map((s, i) => (
            <li key={`${s.lat},${s.lng},${i}`}>
              <button
                type="button"
                onMouseDown={(e) => {
                  // preventDefault stops the input from blurring.
                  // stopPropagation keeps the enclosing <label> from
                  // re-focusing the input mid-selection.
                  // choose() runs synchronously, before the browser
                  // dispatches blur or click — no race.
                  e.preventDefault()
                  e.stopPropagation()
                  choose(s)
                }}
                onMouseEnter={() => setHighlighted(i)}
                className={`block w-full px-3 py-2 text-left text-sm ${
                  i === highlighted ? 'bg-slate-100' : 'hover:bg-slate-50'
                }`}
              >
                <div className="line-clamp-2 text-slate-900">
                  {s.display_name}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}