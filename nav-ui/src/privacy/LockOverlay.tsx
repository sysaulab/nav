import { usePrivacy } from './PrivacyContext'

export function LockOverlay() {
  const { locked, unlock } = usePrivacy()

  if (!locked) return null

  return (
    <div
      className="fixed inset-0 z-50 flex cursor-pointer items-center justify-center backdrop-blur-[10px] transition-all"
      onClick={unlock}
    >
      <div className="rounded-2xl bg-white/90 p-8 text-center shadow-xl backdrop-blur-md">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-slate-100 text-3xl shadow-inner">
          🔒
        </div>
        <h2 className="mt-4 text-xl font-semibold text-slate-900">Session Locked</h2>
        <p className="mt-2 text-sm text-slate-600">Click anywhere to unlock</p>
      </div>
    </div>
  )
}