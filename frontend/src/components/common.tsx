// 小さな共通部品（ダイアログ・切り替えボタン・画像の入力）

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export function Dialog(props: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') props.onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [props])
  return (
    <div className="dialog-backdrop" onPointerDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className={`dialog${props.wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={props.title}>
        <div className="dialog-head">
          <h2>{props.title}</h2>
          <button type="button" className="icon-btn" onClick={props.onClose} aria-label="閉じる">
            ×
          </button>
        </div>
        <div className="dialog-body">{props.children}</div>
        {props.footer && <div className="dialog-foot">{props.footer}</div>}
      </div>
    </div>
  )
}

export function Segmented<T extends string>(props: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  small?: boolean
}) {
  return (
    <div className={`seg${props.small ? ' small' : ''}`} role="group" aria-label={props.label}>
      {props.options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === props.value ? 'on' : undefined}
          aria-pressed={o.value === props.value}
          onClick={() => props.onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** ファイル選択ボタン（スマホではフォトライブラリが開く） */
export function FileButton(props: {
  label: ReactNode
  onFiles: (files: File[]) => void
  multiple?: boolean
  className?: string
  disabled?: boolean
}) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button type="button" className={props.className ?? 'btn'} disabled={props.disabled} onClick={() => ref.current?.click()}>
        {props.label}
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        multiple={props.multiple}
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          if (files.length) props.onFiles(files)
        }}
      />
    </>
  )
}

/** ドラッグ＆ドロップを受ける領域 */
export function DropZone(props: { onFiles: (files: File[]) => void; children: ReactNode; className?: string }) {
  const [over, setOver] = useState(false)
  return (
    <div
      className={`${props.className ?? ''}${over ? ' drop-over' : ''}`}
      onDragOver={(e) => {
        if (Array.from(e.dataTransfer.types).includes('Files')) {
          e.preventDefault()
          setOver(true)
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/'))
        if (files.length) props.onFiles(files)
      }}
    >
      {props.children}
    </div>
  )
}

/** クリップボードから画像を読む（「貼り付け」ボタン用。対応していないブラウザでは Ctrl+V を案内） */
export async function readClipboardImage(): Promise<Blob | null> {
  const nav = navigator as Navigator & { clipboard?: { read?: () => Promise<ClipboardItem[]> } }
  if (!nav.clipboard?.read) return null
  const items = await nav.clipboard.read()
  for (const it of items) {
    const type = it.types.find((t) => t.startsWith('image/'))
    if (type) return it.getType(type)
  }
  return null
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '?'
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} KB`
  return `${n} B`
}
