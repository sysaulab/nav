/** Mirror the `<input accept>` semantics for dropped files. */
export function matchesAccept(file: File, accept: string): boolean {
  if (!accept) return true
  const rules = accept.split(',').map((s) => s.trim().toLowerCase())
  const name = file.name.toLowerCase()
  const mime = (file.type || '').toLowerCase()
  return rules.some((rule) => {
    if (rule.startsWith('.')) return name.endsWith(rule)
    if (rule.endsWith('/*')) return mime.startsWith(rule.slice(0, -1))
    return mime === rule
  })
}