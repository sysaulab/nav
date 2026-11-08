import { useEffect, useRef, useState } from 'react'
import { api, type GeocodeSuggestion } from '../api'

type Props = {
  value: string
  onChange: (value: string) => void
  onSelect: (suggestion: GeocodeSuggestion) => void
  placeholder?: string
  disabled?: boolean
  suggestionsEnabled?: boolean
  isFrozen?: boolean
}

export function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  placeholder,
  disabled,
  suggestionsEnabled = true,
  isFrozen = false,
}: Props) {
  const [suggestions, setSuggestions] = useState<GeocodeSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)

  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | null>(null)
  const skipNextLookupRef = useRef(false)

  useEffect(() => {
    if (!suggestionsEnabled || isFrozen) {
      abortRef.current?.abort()
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      setSuggestions([])
      setOpen(false)
      return
    }

    if (skipNextLookupRef.current) {
      skipNextLookupRef.current = false
      setSuggestions([])
      setOpen(false)
      return
    }

    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    const q = value.trim()
    if (q.length < 2) {
      setSuggestions([])
      setOpen(false)
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
        // silent
      }
    }, 300)
    
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [value, suggestionsEnabled, isFrozen])

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
      e.preventDefault()
      choose(suggestions[highlighted])
    }
  }

  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        placeholder={placeholder}
        className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none ${
          isFrozen ? 'border-blue-300 bg-blue-50 focus:border-blue-500' : 
          suggestions.length > 0 ? 'border-red-300 focus:border-red-500' : 'border-slate-300 focus:border-slate-500'
        }`}
        disabled={disabled}
        autoComplete="off"
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute left-0 right-0 z-10 mt-1 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          {suggestions.map((s, i) => (
            <li key={`${s.lat},${s.lng},${i}`}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); choose(s) }}
                onMouseEnter={() => setHighlighted(i)}
                className={`block w-full px-3 py-2 text-left text-sm ${
                  i === highlighted ? 'bg-slate-100' : 'hover:bg-slate-50'
                }`}
              >
                <div className="line-clamp-2 text-slate-900">{s.display_name}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}