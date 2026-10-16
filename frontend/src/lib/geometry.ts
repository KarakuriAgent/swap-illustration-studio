// 枠（矩形）の計算。座標はすべて A の画像のピクセル。

import type { Box } from '../types'

/** 枠の色（1=赤, 2=青, 3=緑, 4=橙。学習時のマーカーと同じ順） */
export const FRAME_COLORS = ['#E61E1E', '#1E5AE6', '#14AA3C', '#F58C00'] as const
export const MAX_FRAMES = 4

export interface Point {
  x: number
  y: number
}

export function frameColor(index: number): string {
  return FRAME_COLORS[index % FRAME_COLORS.length]
}

/** 2 点から正規化した矩形 */
export function boxFromPoints(a: Point, b: Point): Box {
  return [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)]
}

export function clampBox(b: Box, w: number, h: number): Box {
  const c = (v: number, m: number) => Math.max(0, Math.min(m, v))
  return [c(b[0], w), c(b[1], h), c(b[2], w), c(b[3], h)]
}

export function boxW(b: Box) {
  return b[2] - b[0]
}
export function boxH(b: Box) {
  return b[3] - b[1]
}

export function area(b: Box): number {
  return Math.max(0, boxW(b)) * Math.max(0, boxH(b))
}

export function iou(a: Box, b: Box): number {
  const ix = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]))
  const iy = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]))
  const inter = ix * iy
  const u = area(a) + area(b) - inter
  return u > 0 ? inter / u : 0
}

export function contains(b: Box, p: Point, tol = 0): boolean {
  return p.x >= b[0] - tol && p.x <= b[2] + tol && p.y >= b[1] - tol && p.y <= b[3] + tol
}

/** 角の番号（0=左上, 1=右上, 2=右下, 3=左下）。どの角にも近くなければ -1 */
export function hitCorner(b: Box, p: Point, tol: number): number {
  const corners: Point[] = [
    { x: b[0], y: b[1] },
    { x: b[2], y: b[1] },
    { x: b[2], y: b[3] },
    { x: b[0], y: b[3] },
  ]
  let best = -1
  let bestD = Infinity
  corners.forEach((c, i) => {
    const d = Math.hypot(c.x - p.x, c.y - p.y)
    if (d <= tol && d < bestD) {
      best = i
      bestD = d
    }
  })
  return best
}

/** 角 corner を p に動かした矩形（反対側の角は固定。最小サイズを保つ） */
export function resizeCorner(b: Box, corner: number, p: Point, minSize: number, w: number, h: number): Box {
  let [x0, y0, x1, y1] = b
  const px = Math.max(0, Math.min(w, p.x))
  const py = Math.max(0, Math.min(h, p.y))
  if (corner === 0 || corner === 3) x0 = Math.min(px, x1 - minSize)
  else x1 = Math.max(px, x0 + minSize)
  if (corner === 0 || corner === 1) y0 = Math.min(py, y1 - minSize)
  else y1 = Math.max(py, y0 + minSize)
  return [x0, y0, x1, y1]
}

/** 画像の外に出ないように平行移動 */
export function moveBox(b: Box, dx: number, dy: number, w: number, h: number): Box {
  const bw = boxW(b)
  const bh = boxH(b)
  const x0 = Math.max(0, Math.min(w - bw, b[0] + dx))
  const y0 = Math.max(0, Math.min(h - bh, b[1] + dy))
  return [x0, y0, x0 + bw, y0 + bh]
}

/** 検出した人物のうち、どの枠とも重ならない（置き換えない）人 */
export function untargetedPersons(persons: Box[], frames: Box[], threshold = 0.5): number[] {
  return persons.flatMap((p, i) => (frames.some((f) => iou(p, f) >= threshold) ? [] : [i]))
}

/** 画像上で一番小さい枠を優先して、点を含む枠の番号（なければ -1） */
export function topmostAt(boxes: Box[], p: Point, tol = 0): number {
  let best = -1
  let bestA = Infinity
  boxes.forEach((b, i) => {
    if (contains(b, p, tol) && area(b) < bestA) {
      best = i
      bestA = area(b)
    }
  })
  return best
}

export function roundBox(b: Box): Box {
  return b.map((v) => Math.round(v * 10) / 10) as Box
}
