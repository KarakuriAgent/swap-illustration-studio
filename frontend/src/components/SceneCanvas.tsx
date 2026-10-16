// A の画像の上で枠を指定する（マウス・タッチ共通。Pointer Events）
//
// - 何もないところをドラッグ → 新しい枠を描く（「枠を描く」中は枠の上からでも描ける）
// - 自動検出の候補（点線）をタップ → 枠にする
// - 枠をタップ → 選択（角のハンドルで大きさ調整・ドラッグで移動）。選択中の枠をもう一度タップ → 外す
// - 選択中の枠の × → 外す

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, PointerEvent as RPointerEvent } from 'react'
import type { EditorAction } from '../lib/editor'
import {
  MAX_FRAMES,
  boxFromPoints,
  frameColor,
  hitCorner,
  moveBox,
  resizeCorner,
  topmostAt,
  type Point,
} from '../lib/geometry'
import type { Box, Frame, ImageInfo } from '../types'

interface Props {
  image: ImageInfo
  frames: Frame[]
  selected: string | null
  dispatch: Dispatch<EditorAction>
  /** 枠にしていない検出候補（index は detection.persons の番号） */
  candidates: { index: number; box: Box }[]
  drawMode: boolean
  refsCount: number
  /** 表示上の最大の高さ（CSS の値） */
  maxHeight?: string
  /** 送る画像（A_marked）のプレビューを重ねて表示する */
  overlayUrl?: string | null
  onLimit?: () => void
}

type Drag =
  | { kind: 'draw'; start: Point; cur: Point }
  | { kind: 'frame'; id: string; start: Point; origin: Box; moved: boolean; wasSelected: boolean }
  | { kind: 'resize'; id: string; corner: number }
  | { kind: 'cand'; index: number; box: Box; start: Point }

const TAP_PX = 6

/** 縦横比を保ったまま、幅 100% と最大の高さの両方に収まる大きさ */
export function fitStyle(w: number, h: number, maxHeight?: string) {
  return {
    aspectRatio: `${w} / ${h}`,
    width: maxHeight ? `min(100%, calc(${maxHeight} * ${(w / h).toFixed(4)}))` : '100%',
  }
}

export default function SceneCanvas(props: Props) {
  const { image, frames, selected, dispatch, candidates, drawMode, refsCount } = props
  const svgRef = useRef<SVGSVGElement>(null)
  const [scale, setScale] = useState(1) // 画像 px / 画面 px
  const [drag, setDrag] = useState<Drag | null>(null)
  const W = image.width
  const H = image.height

  useLayoutEffect(() => {
    const el = svgRef.current
    if (!el) return
    const update = () => {
      const w = el.getBoundingClientRect().width
      if (w > 0) setScale(W / w)
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [W])

  // Delete / Backspace で選択中の枠を外す（入力欄にいるときは除く）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        e.preventDefault()
        dispatch({ type: 'remove', id: selected })
      } else if (e.key === 'Escape') {
        dispatch({ type: 'select', id: null })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, dispatch])

  const toImage = (e: RPointerEvent): Point => {
    const r = svgRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(W, ((e.clientX - r.left) * W) / r.width)),
      y: Math.max(0, Math.min(H, ((e.clientY - r.top) * H) / r.height)),
    }
  }

  const handleTol = (e: RPointerEvent) => (e.pointerType === 'touch' ? 26 : 14) * scale
  const minSize = Math.max(8, Math.min(W, H) * 0.02)

  const onDown = (e: RPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    const p = toImage(e)
    svgRef.current?.setPointerCapture(e.pointerId)
    if (!drawMode) {
      // 角（選択中の枠を優先）
      const order = [...frames].sort((a, b) => (a.id === selected ? -1 : b.id === selected ? 1 : 0))
      for (const f of order) {
        const c = hitCorner(f.box, p, handleTol(e))
        if (c >= 0) {
          dispatch({ type: 'begin' })
          dispatch({ type: 'select', id: f.id })
          setDrag({ kind: 'resize', id: f.id, corner: c })
          return
        }
      }
      const fi = topmostAt(
        frames.map((f) => f.box),
        p,
      )
      if (fi >= 0) {
        const f = frames[fi]
        setDrag({ kind: 'frame', id: f.id, start: p, origin: f.box, moved: false, wasSelected: f.id === selected })
        return
      }
      const ci = topmostAt(
        candidates.map((c) => c.box),
        p,
      )
      if (ci >= 0) {
        setDrag({ kind: 'cand', index: candidates[ci].index, box: candidates[ci].box, start: p })
        return
      }
    }
    setDrag({ kind: 'draw', start: p, cur: p })
  }

  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (!drag) return
    const p = toImage(e)
    if (drag.kind === 'draw') {
      setDrag({ ...drag, cur: p })
    } else if (drag.kind === 'resize') {
      const f = frames.find((x) => x.id === drag.id)
      if (f) dispatch({ type: 'move', id: f.id, box: resizeCorner(f.box, drag.corner, p, minSize, W, H) })
    } else if (drag.kind === 'frame') {
      const dist = Math.hypot(p.x - drag.start.x, p.y - drag.start.y) / scale
      if (!drag.moved && dist < TAP_PX) return
      if (!drag.moved) {
        dispatch({ type: 'begin' })
        dispatch({ type: 'select', id: drag.id })
      }
      dispatch({ type: 'move', id: drag.id, box: moveBox(drag.origin, p.x - drag.start.x, p.y - drag.start.y, W, H) })
      if (!drag.moved) setDrag({ ...drag, moved: true })
    } else if (drag.kind === 'cand') {
      const dist = Math.hypot(p.x - drag.start.x, p.y - drag.start.y) / scale
      if (dist >= TAP_PX) setDrag({ kind: 'draw', start: drag.start, cur: p })
    }
  }

  const add = (box: Box, detIndex: number | null) => {
    if (frames.length >= MAX_FRAMES) {
      props.onLimit?.()
      return
    }
    dispatch({ type: 'add', box, detIndex, refsCount })
  }

  const onUp = (e: RPointerEvent<SVGSVGElement>) => {
    if (!drag) return
    svgRef.current?.releasePointerCapture(e.pointerId)
    if (drag.kind === 'draw') {
      const b = boxFromPoints(drag.start, drag.cur)
      if (b[2] - b[0] >= minSize && b[3] - b[1] >= minSize) add(b, null)
      else dispatch({ type: 'select', id: null })
    } else if (drag.kind === 'frame' && !drag.moved) {
      if (drag.wasSelected) dispatch({ type: 'remove', id: drag.id })
      else dispatch({ type: 'select', id: drag.id })
    } else if (drag.kind === 'cand') {
      add(drag.box, drag.index)
    }
    setDrag(null)
  }

  const sw = 3 * scale
  const badgeR = 13 * scale
  const handleR = 7 * scale
  const fontSize = 15 * scale
  const draft = drag?.kind === 'draw' ? boxFromPoints(drag.start, drag.cur) : null

  return (
    <div className="scene-canvas" style={{ maxHeight: props.maxHeight }}>
      <div className="scene-canvas-inner" style={fitStyle(W, H, props.maxHeight)}>
        <img src={props.overlayUrl || image.url} alt="シーン A" draggable={false} />
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className={drawMode ? 'draw-mode' : undefined}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={() => setDrag(null)}
          role="application"
          aria-label="枠の指定（ドラッグで枠を描く・タップで選択）"
        >
          {!props.overlayUrl &&
            candidates.map((c) => (
              <g key={`c${c.index}`} className="candidate">
                <rect
                  x={c.box[0]}
                  y={c.box[1]}
                  width={c.box[2] - c.box[0]}
                  height={c.box[3] - c.box[1]}
                  fill="rgba(255,255,255,0.08)"
                  stroke="#FFFFFF"
                  strokeWidth={2.5 * scale}
                  strokeDasharray={`${8 * scale} ${6 * scale}`}
                />
                <rect
                  x={c.box[0]}
                  y={c.box[1]}
                  width={c.box[2] - c.box[0]}
                  height={c.box[3] - c.box[1]}
                  fill="none"
                  stroke="#16181C"
                  strokeWidth={1.2 * scale}
                  strokeDasharray={`${8 * scale} ${6 * scale}`}
                  strokeDashoffset={7 * scale}
                />
                <text
                  x={c.box[0] + 6 * scale}
                  y={c.box[1] + 18 * scale}
                  fontSize={12 * scale}
                  className="candidate-label"
                  paintOrder="stroke"
                  stroke="#FFFFFF"
                  strokeWidth={3 * scale}
                >
                  検出：タップで追加
                </text>
              </g>
            ))}
          {!props.overlayUrl &&
            frames.map((f, i) => {
              const col = frameColor(i)
              const [x0, y0, x1, y1] = f.box
              const isSel = f.id === selected
              return (
                <g key={f.id}>
                  <rect
                    x={x0}
                    y={y0}
                    width={x1 - x0}
                    height={y1 - y0}
                    fill={isSel ? `${col}22` : 'rgba(0,0,0,0)'}
                    stroke={col}
                    strokeWidth={isSel ? sw * 1.4 : sw}
                    rx={6 * scale}
                  />
                  <circle cx={x0 + badgeR + 4 * scale} cy={y0 + badgeR + 4 * scale} r={badgeR} fill={col} stroke="#fff" strokeWidth={2 * scale} />
                  <text
                    x={x0 + badgeR + 4 * scale}
                    y={y0 + badgeR + 4 * scale}
                    fontSize={fontSize}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className="badge-text"
                  >
                    {i + 1}
                  </text>
                  {isSel &&
                    [
                      [x0, y0],
                      [x1, y0],
                      [x1, y1],
                      [x0, y1],
                    ].map(([cx, cy], k) => (
                      <circle key={k} cx={cx} cy={cy} r={handleR} fill="#fff" stroke={col} strokeWidth={2.5 * scale} />
                    ))}
                </g>
              )
            })}
          {draft && (
            <rect
              x={draft[0]}
              y={draft[1]}
              width={draft[2] - draft[0]}
              height={draft[3] - draft[1]}
              fill="rgba(22,24,28,0.08)"
              stroke={frameColor(frames.length)}
              strokeWidth={sw}
              strokeDasharray={`${10 * scale} ${6 * scale}`}
            />
          )}
        </svg>
        {!props.overlayUrl &&
          frames
            .filter((f) => f.id === selected)
            .map((f) => (
              <button
                key={f.id}
                type="button"
                className="frame-remove"
                style={{
                  left: `${(Math.min(f.box[2], W) / W) * 100}%`,
                  top: `${(f.box[1] / H) * 100}%`,
                }}
                onClick={() => dispatch({ type: 'remove', id: f.id })}
                aria-label="この枠を外す"
              >
                ×
              </button>
            ))}
      </div>
    </div>
  )
}
