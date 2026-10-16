// 枠の編集状態（元に戻す付き）

import type { Box, Frame, Outfit } from '../types'
import { MAX_FRAMES } from './geometry'

export interface EditorState {
  frames: Frame[]
  /** 元に戻す用のスナップショット（新しいものが末尾） */
  past: Frame[][]
  selected: string | null
}

export type EditorAction =
  | { type: 'add'; box: Box; detIndex?: number | null; refsCount: number }
  | { type: 'begin' }
  | { type: 'move'; id: string; box: Box }
  | { type: 'remove'; id: string }
  | { type: 'select'; id: string | null }
  | { type: 'setRef'; id: string; ref: number | null }
  | { type: 'setOutfit'; id: string; outfit: Outfit }
  | { type: 'setAllOutfit'; outfit: Outfit }
  | { type: 'reset'; frames: Frame[] }
  | { type: 'clear' }
  | { type: 'undo' }
  | { type: 'refRemoved'; index: number }
  | { type: 'refMoved'; from: number; to: number }

export const initialEditor: EditorState = { frames: [], past: [], selected: null }

const HISTORY_LIMIT = 50

let seq = 0
export function newId(prefix = 'f'): string {
  seq += 1
  return `${prefix}${Date.now().toString(36)}${seq}`
}

function push(state: EditorState): Frame[][] {
  return [...state.past, state.frames].slice(-HISTORY_LIMIT)
}

/** まだどの枠にも割り当てていない B の番号（無ければ null） */
export function firstFreeRef(frames: Frame[], refsCount: number): number | null {
  for (let i = 0; i < refsCount; i++) {
    if (!frames.some((f) => f.ref === i)) return i
  }
  return null
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case 'add': {
      if (state.frames.length >= MAX_FRAMES) return state
      const frame: Frame = {
        id: newId(),
        box: action.box,
        ref: firstFreeRef(state.frames, action.refsCount),
        outfit: 'b',
        detIndex: action.detIndex ?? null,
      }
      return { frames: [...state.frames, frame], past: push(state), selected: frame.id }
    }
    case 'begin':
      // ドラッグの開始時に 1 回だけ記録する（ドラッグ中の move は記録しない）
      return { ...state, past: push(state) }
    case 'move':
      return { ...state, frames: state.frames.map((f) => (f.id === action.id ? { ...f, box: action.box } : f)) }
    case 'remove':
      return {
        frames: state.frames.filter((f) => f.id !== action.id),
        past: push(state),
        selected: state.selected === action.id ? null : state.selected,
      }
    case 'select':
      return { ...state, selected: action.id }
    case 'setRef':
      return {
        ...state,
        past: push(state),
        frames: state.frames.map((f) => (f.id === action.id ? { ...f, ref: action.ref } : f)),
      }
    case 'setOutfit':
      return {
        ...state,
        past: push(state),
        frames: state.frames.map((f) => (f.id === action.id ? { ...f, outfit: action.outfit } : f)),
      }
    case 'setAllOutfit':
      return { ...state, past: push(state), frames: state.frames.map((f) => ({ ...f, outfit: action.outfit })) }
    case 'reset':
      return { frames: action.frames, past: [], selected: null }
    case 'clear':
      if (!state.frames.length) return state
      return { frames: [], past: push(state), selected: null }
    case 'undo': {
      if (!state.past.length) return state
      const prev = state.past[state.past.length - 1]
      return {
        frames: prev,
        past: state.past.slice(0, -1),
        selected: prev.some((f) => f.id === state.selected) ? state.selected : null,
      }
    }
    case 'refRemoved': {
      const remap = (r: number | null) => (r === null || r === action.index ? null : r > action.index ? r - 1 : r)
      return {
        ...state,
        frames: state.frames.map((f) => ({ ...f, ref: remap(f.ref) })),
        past: state.past.map((fs) => fs.map((f) => ({ ...f, ref: remap(f.ref) }))),
      }
    }
    case 'refMoved': {
      // B の並べ替え（from を to へ）。枠の割り当ては同じ人物を指したままにする
      const { from, to } = action
      const remap = (r: number | null) => {
        if (r === null) return r
        if (r === from) return to
        if (from < to && r > from && r <= to) return r - 1
        if (from > to && r >= to && r < from) return r + 1
        return r
      }
      return {
        ...state,
        frames: state.frames.map((f) => ({ ...f, ref: remap(f.ref) })),
        past: state.past.map((fs) => fs.map((f) => ({ ...f, ref: remap(f.ref) }))),
      }
    }
  }
}

export function moveItem<T>(list: T[], from: number, to: number): T[] {
  const out = list.slice()
  const [it] = out.splice(from, 1)
  out.splice(to, 0, it)
  return out
}
