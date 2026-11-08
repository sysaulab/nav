import { usePrivacy } from './PrivacyContext'

export function LockButton() {
  const { lock, locked } = usePrivacy()

  // Don't show the lock button if we're already on the lock screen
  if (locked) return null

  return (
    <button
      onClick={lock}
      className="fixed bottom-4 right-4 z-30 rounded-full bg-slate-900 px-3 py-2 text-xs font-medium text-white shadow-md hover:bg-slate-800"
      title="Lock screen"
    >
      🔒
    </button>
  )
}