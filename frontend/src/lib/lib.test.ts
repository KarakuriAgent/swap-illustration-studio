import { describe, expect, it } from 'vitest'
import type { Box, Frame, RefImage } from '../types'
import { editorReducer, firstFreeRef, initialEditor, moveItem } from './editor'
import { boxFromPoints, hitCorner, iou, moveBox, resizeCorner, topmostAt, untargetedPersons } from './geometry'
import { generateRequest, sceneSpec, validate } from './request'

const box = (x0: number, y0: number, x1: number, y1: number): Box => [x0, y0, x1, y1]

describe('geometry', () => {
  it('boxFromPoints normalizes', () => {
    expect(boxFromPoints({ x: 10, y: 20 }, { x: 0, y: 5 })).toEqual([0, 5, 10, 20])
  })
  it('hitCorner finds nearest corner', () => {
    const b = box(0, 0, 100, 100)
    expect(hitCorner(b, { x: 98, y: 97 }, 10)).toBe(2)
    expect(hitCorner(b, { x: 50, y: 50 }, 10)).toBe(-1)
  })
  it('resizeCorner keeps opposite corner and min size', () => {
    expect(resizeCorner(box(10, 10, 100, 100), 0, { x: 0, y: 0 }, 5, 200, 200)).toEqual([0, 0, 100, 100])
    expect(resizeCorner(box(10, 10, 100, 100), 2, { x: 5, y: 5 }, 20, 200, 200)).toEqual([10, 10, 30, 30])
    expect(resizeCorner(box(10, 10, 100, 100), 1, { x: 500, y: -5 }, 5, 200, 200)).toEqual([10, 0, 200, 100])
  })
  it('moveBox stays inside', () => {
    expect(moveBox(box(0, 0, 50, 50), -10, 300, 100, 100)).toEqual([0, 50, 50, 100])
  })
  it('iou / untargeted persons', () => {
    expect(iou(box(0, 0, 10, 10), box(0, 0, 10, 10))).toBe(1)
    expect(iou(box(0, 0, 10, 10), box(20, 20, 30, 30))).toBe(0)
    const persons = [box(0, 0, 10, 10), box(20, 0, 30, 10), box(40, 0, 50, 10)]
    expect(untargetedPersons(persons, [box(1, 0, 10, 10)])).toEqual([1, 2])
  })
  it('topmostAt prefers the smaller box', () => {
    expect(topmostAt([box(0, 0, 100, 100), box(10, 10, 20, 20)], { x: 15, y: 15 })).toBe(1)
    expect(topmostAt([box(0, 0, 100, 100)], { x: 150, y: 15 })).toBe(-1)
  })
})

describe('editor', () => {
  it('adds frames with free refs, max 4, and undo', () => {
    let s = initialEditor
    for (let i = 0; i < 5; i++) s = editorReducer(s, { type: 'add', box: box(i, 0, i + 10, 10), refsCount: 2 })
    expect(s.frames.length).toBe(4)
    expect(s.frames.map((f) => f.ref)).toEqual([0, 1, null, null])
    s = editorReducer(s, { type: 'undo' })
    expect(s.frames.length).toBe(3)
    s = editorReducer(s, { type: 'remove', id: s.frames[0].id })
    expect(s.frames.length).toBe(2)
    s = editorReducer(s, { type: 'undo' })
    expect(s.frames.length).toBe(3)
  })
  it('drag records one undo step', () => {
    let s = editorReducer(initialEditor, { type: 'add', box: box(0, 0, 10, 10), refsCount: 1 })
    const id = s.frames[0].id
    s = editorReducer(s, { type: 'begin' })
    s = editorReducer(s, { type: 'move', id, box: box(5, 0, 15, 10) })
    s = editorReducer(s, { type: 'move', id, box: box(9, 0, 19, 10) })
    expect(s.frames[0].box).toEqual([9, 0, 19, 10])
    s = editorReducer(s, { type: 'undo' })
    expect(s.frames[0].box).toEqual([0, 0, 10, 10])
  })
  it('remaps refs when B is removed or moved', () => {
    let s = initialEditor
    for (let i = 0; i < 3; i++) s = editorReducer(s, { type: 'add', box: box(i, 0, i + 1, 1), refsCount: 3 })
    expect(s.frames.map((f) => f.ref)).toEqual([0, 1, 2])
    const moved = editorReducer(s, { type: 'refMoved', from: 0, to: 2 })
    expect(moved.frames.map((f) => f.ref)).toEqual([2, 0, 1])
    const removed = editorReducer(s, { type: 'refRemoved', index: 1 })
    expect(removed.frames.map((f) => f.ref)).toEqual([0, null, 1])
  })
  it('firstFreeRef / moveItem', () => {
    expect(firstFreeRef([{ ref: 0 } as Frame], 2)).toBe(1)
    expect(firstFreeRef([{ ref: 0 } as Frame], 1)).toBe(null)
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a'])
  })
})

describe('request', () => {
  const img = { id: 'a'.repeat(20), width: 100, height: 100, url: '/x' }
  const ref: RefImage = { key: 'r', image: { ...img, id: 'b'.repeat(20) }, original: img }
  const frame = (ref: number | null, b: Box): Frame => ({ id: String(b[0]), box: b, ref, outfit: 'b', detIndex: null })
  const base = { scene: img, refs: [ref], detection: null, mode: 'marked' as const, faceMode: 'auto' as const, template: 0 }

  it('validates', () => {
    expect(validate({ ...base, scene: null, frames: [] })).toMatch('シーン')
    expect(validate({ ...base, frames: [] })).toMatch('枠')
    expect(validate({ ...base, frames: [frame(null, box(0, 0, 1, 1))] })).toMatch('枠 1')
    expect(validate({ ...base, frames: [frame(0, box(0, 0, 1, 1))] })).toBeNull()
  })
  it('builds others from detection not covered by frames', () => {
    const detection = {
      available: true,
      persons: [{ box: box(0, 0, 40, 100), score: 1 }, { box: box(60, 0, 100, 100), score: 1 }],
      faces: [{ box: box(10, 5, 30, 25), score: 1 }],
      message: '',
    }
    const spec = sceneSpec({ ...base, detection, frames: [frame(0, box(1, 0, 40, 100))] })!
    expect(spec.others).toEqual([{ box: [60, 0, 100, 100] }])
    expect(spec.faces).toEqual([[10, 5, 30, 25]])
    const req = generateRequest({ ...base, detection, frames: [frame(0, box(1, 0, 40, 100))] },
      { model: 'turbo', strength: 1, seed: 11, count: 2 }, '  ')
    expect(req.refs).toEqual(['b'.repeat(20)])
    expect(req.prompt_override).toBeNull()
    expect(req.settings).toEqual({ model: 'turbo', strength: 1, seed: 11, count: 2 })
  })
})
