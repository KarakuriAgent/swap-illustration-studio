// API とやり取りする型（backend/app/models.py・jobs.py の job_out に対応）

export type Box = [number, number, number, number]

export interface ImageInfo {
  id: string
  width: number
  height: number
  url: string
}

/** 入れたい人物 B（1 枚に 1 人）。original は切り抜く前の画像（切り抜き直し用）。 */
export interface RefImage {
  key: string
  image: ImageInfo
  original: ImageInfo
}

export type Outfit = 'b' | 'a'
export type Mode = 'marked' | 'position'
export type FaceMode = 'auto' | 'on' | 'off'
export type ModelKind = 'turbo' | 'base'
export type Target = 'local' | 'cloud'

/** A の上の枠（リストの順が枠番号 1〜4） */
export interface Frame {
  id: string
  box: Box
  /** 入れる B（refs の何番目か）。null = 未割り当て */
  ref: number | null
  outfit: Outfit
  /** 自動検出の候補から付けた枠なら、その候補の番号 */
  detIndex: number | null
}

export interface Detection {
  available: boolean
  persons: { box: Box; score: number }[]
  faces: { box: Box; score: number }[]
  message: string
}

export interface GenSettings {
  model: ModelKind
  strength: number
  /** null = ランダム */
  seed: number | null
  count: number
}

export interface InstructionResult {
  prompt: string
  face: boolean
  warnings: string[]
}

export interface JobResult {
  file: string
  seed: number
  elapsed: number
  url: string
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled'

export interface GenerateRequest {
  scene_id: string
  refs: string[]
  targets: { box: Box; ref: number; outfit: Outfit }[]
  others: { box: Box }[]
  faces: Box[]
  mode: Mode
  face_mode: FaceMode
  template: number
  prompt_override: string | null
  settings: {
    target?: Target | null
    model: ModelKind
    lora_name?: string | null
    strength: number
    seed: number | null
    count: number
  }
}

export interface Job {
  id: string
  created_at: number
  finished_at: number | null
  status: JobStatus
  message: string | null
  error: string | null
  progress: number
  prompt: string
  request: GenerateRequest
  settings: {
    target: Target
    model: ModelKind
    lora_name: string
    strength: number
    seed: number
    count: number
    face: boolean
    prompt_edited: boolean
  }
  parent_id: string | null
  inputs: Record<string, string>
  results: JobResult[]
}

export interface AppSettings {
  target: Target
  local_comfy_url: string
  local_comfy_url_default: string
  comfy_cloud_api_key_set: boolean
  hf_token_set: boolean
  lora_name_local: string
  lora_name_cloud: string
  lora_hf_repo: string
  lora_hf_repo_effective: string
  lora_sha256: string
  lora_sha256_effective: string
  model_urls: Record<string, string>
  comfy_models_dir: string | null
  token_required: boolean
}

export interface Health {
  app: string
  version: string
  target: Target
  comfy_url: string
  comfy_ok: boolean
  comfy_error: string | null
}

export interface SetupDownload {
  key: string
  status: 'downloading' | 'verifying' | 'done' | 'error' | 'paused'
  received: number
  total: number | null
  error: string | null
  message?: string
}

export interface SetupItem {
  key: string
  folder: string
  filename: string
  used_by: string[]
  ok: boolean
  in_comfy: boolean | null
  file: 'present' | 'size_mismatch' | 'partial' | 'absent' | 'unknown'
  source: { kind: 'url' | 'none'; url: string | null; size: number | null; sha256: string | null }
  download: SetupDownload | null
}

export interface SetupStatus {
  models_dir: { configured: boolean; exists: boolean; writable: boolean; path: string | null }
  comfy_checked: boolean
  comfy_error: string | null
  items: SetupItem[]
  all_ok: boolean
  target: Target
}
