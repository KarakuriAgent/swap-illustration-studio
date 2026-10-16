// B の切り抜き（設定画などから 1 人の全身・バストアップを矩形で切り出す）

import { useRef, useState } from 'react'
import type { PointerEvent as RPointerEvent } from 'react'
import { boxFromPoints, hitCorner, moveBox, resizeCorner, contains, type Point } from '../lib/geometry'
import type { Box, ImageInfo } from '../types'
import { Dialog } from './common'
import { fitStyle } from './SceneCanvas'

type Drag = { kind: 'draw'; start: Point } | { kind: 'move'; start: Point; origin: Box } | { kind: 'resize'; corner: number }

export default function CropDialog(props: {
  image: ImageInfo
  busy?: boolean
  onCancel: () => void
  onCrop: (box: Box) => void
  onUseWhole: () => void
}) {
  const { image } = props
  const W = image.width
  const H = image.height
  const svgRef = useRef<SVGSVGElement>(null)
  const [box, setBox] = useState<Box | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)

  const scale = () => {
    const r = svgRef.current?.getBoundingClientRect()
    return r && r.width ? W / r.width : 1
  }
  const toImage = (e: RPointerEvent): Point => {
    const r = svgRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(W, ((e.clientX - r.left) * W) / r.width)),
      y: Math.max(0, Math.min(H, ((e.clientY - r.top) * H) / r.height)),
    }
  }
  const minSize = Math.max(16, Math.min(W, H) * 0.03)

  const onDown = (e: RPointerEvent<SVGSVGElement>) => {
    const p = toImage(e)
    svgRef.current?.setPointerCapture(e.pointerId)
    if (box) {
      const c = hitCorner(box, p, (e.pointerType === 'touch' ? 26 : 14) * scale())
      if (c >= 0) return setDrag({ kind: 'resize', corner: c })
      if (contains(box, p)) return setDrag({ kind: 'move', start: p, origin: box })
    }
    setDrag({ kind: 'draw', start: p })
    setBox(null)
  }
  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (!drag) return
    const p = toImage(e)
    if (drag.kind === 'draw') setBox(boxFromPoints(drag.start, p))
    else if (drag.kind === 'move') setBox(moveBox(drag.origin, p.x - drag.start.x, p.y - drag.start.y, W, H))
    else if (box) setBox(resizeCorner(box, drag.corner, p, minSize, W, H))
  }
  const onUp = () => {
    setDrag(null)
    if (box && (box[2] - box[0] < minSize || box[3] - box[1] < minSize)) setBox(null)
  }

  const s = 1 // 描画は vector-effect で太さを固定
  return (
    <Dialog
      title="人物（B）を切り抜く"
      onClose={props.onCancel}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={props.onUseWhole} disabled={props.busy}>
            切り抜かずに使う
          </button>
          <button type="button" className="btn btn-primary" disabled={!box || props.busy} onClick={() => box && props.onCrop(box)}>
            切り抜いて使う
          </button>
        </>
      }
    >
      <p className="hint">1 人の全身かバストアップを囲んでください（設定画・集合絵などから 1 人だけを切り出せます）。</p>
      <div className="crop-wrap">
        <div className="scene-canvas-inner" style={fitStyle(W, H, '62vh')}>
          <img src={image.url} alt="切り抜く画像" draggable={false} />
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
          >
            {box && (
              <>
                <path
                  d={`M0 0H${W}V${H}H0Z M${box[0]} ${box[1]}V${box[3]}H${box[2]}V${box[1]}Z`}
                  fill="rgba(22,24,28,0.45)"
                  fillRule="evenodd"
                />
                <rect
                  x={box[0]}
                  y={box[1]}
                  width={box[2] - box[0]}
                  height={box[3] - box[1]}
                  fill="none"
                  stroke="#fff"
                  strokeWidth={2 * s}
                  vectorEffect="non-scaling-stroke"
                />
                {[
                  [box[0], box[1]],
                  [box[2], box[1]],
                  [box[2], box[3]],
                  [box[0], box[3]],
                ].map(([x, y], k) => (
                  <rect
                    key={k}
                    x={x - 6 * scale()}
                    y={y - 6 * scale()}
                    width={12 * scale()}
                    height={12 * scale()}
                    fill="#fff"
                    stroke="#16181C"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </>
            )}
          </svg>
        </div>
      </div>
    </Dialog>
  )
}
