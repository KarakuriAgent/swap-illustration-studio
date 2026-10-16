// 編集状態から API のリクエストを組み立てる

import type { Detection, FaceMode, Frame, GenSettings, GenerateRequest, ImageInfo, Mode, RefImage } from '../types'
import { roundBox, untargetedPersons } from './geometry'

export interface SceneInput {
  scene: ImageInfo | null
  frames: Frame[]
  refs: RefImage[]
  detection: Detection | null
  mode: Mode
  faceMode: FaceMode
  template: number
}

export type SceneSpec = Omit<GenerateRequest, 'refs' | 'prompt_override' | 'settings'>

/** 生成できない理由（できるなら null） */
export function validate(input: SceneInput): string | null {
  if (!input.scene) return 'シーン（A）の画像を選んでください'
  if (!input.refs.length) return '入れたい人物（B）の画像を追加してください'
  if (!input.frames.length) return 'A の上で置き換える人物に枠を付けてください'
  const missing = input.frames.findIndex((f) => f.ref === null || f.ref >= input.refs.length)
  if (missing >= 0) return `枠 ${missing + 1} に入れる人物（B）を選んでください`
  return null
}

/** 指示文・A_marked の組み立てに要る部分（枠に B が無くても作れる。ref は仮に 0） */
export function sceneSpec(input: SceneInput): SceneSpec | null {
  if (!input.scene || !input.frames.length) return null
  const det = input.detection
  const persons = det?.persons.map((p) => p.box) ?? []
  const others = untargetedPersons(
    persons,
    input.frames.map((f) => f.box),
  ).map((i) => ({ box: roundBox(persons[i]) }))
  return {
    scene_id: input.scene.id,
    targets: input.frames.map((f) => ({ box: roundBox(f.box), ref: Math.max(0, f.ref ?? 0), outfit: f.outfit })),
    others,
    faces: det?.faces.map((f) => roundBox(f.box)) ?? [],
    mode: input.mode,
    face_mode: input.faceMode,
    template: input.template,
  }
}

export function generateRequest(
  input: SceneInput,
  gen: GenSettings,
  promptOverride: string | null,
): GenerateRequest {
  const spec = sceneSpec(input)
  if (!spec) throw new Error(validate(input) ?? '入力が足りません')
  return {
    ...spec,
    refs: input.refs.map((r) => r.image.id),
    prompt_override: promptOverride && promptOverride.trim() ? promptOverride : null,
    settings: {
      model: gen.model,
      strength: gen.strength,
      seed: gen.seed,
      count: gen.count,
    },
  }
}

/** 0〜2^31-1 のランダムなシード */
export function randomSeed(): number {
  return Math.floor(Math.random() * 2147483647)
}
