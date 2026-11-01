import { useEffect, useRef, useState } from 'react'

/**
 * File picker + drop target. Presents as a single dashed-border zone;
 * clicking opens the OS picker, dropping a file invokes onFiles.
 *
 * Both paths call onFiles with the same argument type (File[]) so the
 * caller handles filtering, upload, and errors in one place.
 */
export default function FileDropzone({
  onFiles,
  accept,
  disabled,
  children,
}: {
  onFiles: (files: File[]) => void
  accept?: string
  disabled?: boolean
  children: React.ReactNode
}) {
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // Swallow drops that miss the zone. While a dropzone is on the page,
  // the browser's default "navigate to the dropped file" is almost never
  // what the user wanted. Scoped to file drags only, so text selections
  // elsewhere in the app keep their native behavior.
  useEffect(() => {
    function prevent(e: DragEvent) {
      if (e.dataTransfer?.types.includes('Files')) e.preventDefault()
    }
    document.addEventListener('dragover', prevent)
    document.addEventListener('drop', prevent)
    return () => {
      document.removeEventListener('dragover', prevent)
      document.removeEventListener('drop', prevent)
    }
  }, [])

  function isFileDrag(e: React.DragEvent) {
    return e.dataTransfer.types.includes('Files')
  }

  function onDragEnter(e: React.DragEvent) {
    if (disabled) return
    if (!isFileDrag(e)) return
    e.preventDefault()
    dragDepth.current += 1
    if (dragDepth.current === 1) setDragging(true)
  }

  function onDragOver(e: React.DragEvent) {
    if (disabled) return
    if (!isFileDrag(e)) return
    // MUST preventDefault — otherwise the drop event never fires.
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  function onDragLeave() {
    if (disabled) return
    dragDepth.current -= 1
    if (dragDepth.current <= 0) {
      dragDepth.current = 0
      setDragging(false)
    }
  }

  function onDrop(e: React.DragEvent) {
    if (disabled) return
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onFiles(files)
  }

  const base =
    'block cursor-pointer rounded-xl border-2 border-dashed p-6 text-center text-sm transition-colors'
  const idle = 'border-slate-300 bg-white text-slate-500 hover:border-slate-400'
  const active = 'border-emerald-500 bg-emerald-50 text-emerald-700'
  const inert = 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400'

  return (
    <label
      className={`${base} ${disabled ? inert : dragging ? active : idle}`}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        disabled={disabled}
        className="hidden"
        accept={accept}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          // Reset so picking the same file again still fires onChange.
          if (inputRef.current) inputRef.current.value = ''
          if (files.length > 0) onFiles(files)
        }}
      />
      {children}
    </label>
  )
}