// 結果と元の画像を左右ドラッグで見比べる（境目より左 = 結果、右 = 元の画像）

import { useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as RPointerEvent } from 'react'
import { fitStyle } from './SceneCanvas'

export default function CompareSlider(props: { result: string; original: string; width: number; height: number; maxHeight?: string }) {
  const [pos, setPos] = useState(50)
  const ref = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const update = (e: RPointerEvent) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    setPos(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)))
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') setPos((p) => Math.max(0, p - 5))
    if (e.key === 'ArrowRight') setPos((p) => Math.min(100, p + 5))
  }

  return (
    <div
      ref={ref}
      className="compare"
      style={fitStyle(props.width, props.height, props.maxHeight)}
      onPointerDown={(e) => {
        dragging.current = true
        ref.current?.setPointerCapture(e.pointerId)
        update(e)
      }}
      onPointerMove={(e) => dragging.current && update(e)}
      onPointerUp={() => (dragging.current = false)}
      onPointerCancel={() => (dragging.current = false)}
    >
      <img src={props.original} alt="元の画像" draggable={false} />
      <img src={props.result} alt="結果" draggable={false} style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} />
      <div className="compare-line" style={{ left: `${pos}%` }}>
        <span
          className="compare-handle"
          role="slider"
          tabIndex={0}
          aria-label="結果と元の画像の境目"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pos)}
          onKeyDown={onKey}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M6 4L2 8l4 4M10 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </div>
      <span className="compare-tag left">結果</span>
      <span className="compare-tag right">元の画像</span>
    </div>
  )
}
