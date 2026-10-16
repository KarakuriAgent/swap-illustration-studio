// バックエンド API の呼び出し

import type {
  AppSettings,
  Box,
  Detection,
  GenerateRequest,
  Health,
  ImageInfo,
  InstructionResult,
  Job,
  SetupDownload,
  SetupStatus,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** 401 を受けたときに呼ぶ（App がログイン画面に切り替える） */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

/** FastAPI のエラー本文（detail が文字列 or 検証エラーの配列）を人が読める文にする */
export function errorText(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          const loc = Array.isArray(e?.loc) ? e.loc.filter((x: unknown) => x !== 'body').join('.') : ''
          return loc ? `${loc}: ${e?.msg ?? ''}` : String(e?.msg ?? '')
        })
        .join(' / ')
    }
  }
  if (status === 0) return 'サーバーに接続できません'
  return `エラーが発生しました（HTTP ${status}）`
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'サーバーに接続できません（アプリが起動しているか、ネットワークを確認してください）')
  }
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !path.startsWith('/api/auth/')) onUnauthorized()
    throw new ApiError(res.status, errorText(data, res.status))
  }
  return data as T
}

export const api = {
  authStatus: () => request<{ required: boolean; ok: boolean }>('GET', '/api/auth/status'),
  login: (token: string) => request<{ ok: boolean }>('POST', '/api/auth/login', { token }),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),

  health: () => request<Health>('GET', '/api/health'),
  settings: () => request<AppSettings>('GET', '/api/settings'),
  saveSettings: (s: Partial<Record<string, unknown>>) => request<AppSettings>('PUT', '/api/settings', s),
  loras: (target?: string) =>
    request<{ files: string[]; error: string | null }>('GET', `/api/loras${target ? `?target=${target}` : ''}`),

  uploadImage: (file: Blob, name = 'image.png') => {
    const fd = new FormData()
    fd.append('file', file, name)
    return request<ImageInfo>('POST', '/api/images', fd, true)
  },
  imageInfo: (id: string) => request<ImageInfo>('GET', `/api/images/${id}/info`),
  crop: (id: string, box: Box) => request<ImageInfo>('POST', `/api/images/${id}/crop`, { box }),
  detect: (imageId: string) => request<Detection>('POST', '/api/detect', { image_id: imageId }),

  instruction: (spec: Omit<GenerateRequest, 'refs' | 'prompt_override' | 'settings'>) =>
    request<InstructionResult>('POST', '/api/instruction', spec),
  previewMarked: async (spec: Omit<GenerateRequest, 'refs' | 'prompt_override' | 'settings'>): Promise<string> => {
    const res = await fetch('/api/preview-marked', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec),
    })
    if (!res.ok) {
      let body: unknown = null
      try {
        body = await res.json()
      } catch {
        /* 本文なし */
      }
      throw new ApiError(res.status, errorText(body, res.status))
    }
    return URL.createObjectURL(await res.blob())
  },

  generate: (req: GenerateRequest) => request<Job>('POST', '/api/jobs', req),
  job: (id: string) => request<Job>('GET', `/api/jobs/${id}`),
  cancel: (id: string) => request<Job>('POST', `/api/jobs/${id}/cancel`),
  /** 結果を受け取ったあとで呼ぶ（サーバー側の一時ファイルを消す。履歴は残さない） */
  discardJob: (id: string) => request<{ ok: boolean }>('DELETE', `/api/jobs/${id}`),
  /** 画像をブラウザのメモリ（blob: URL）に取り込む */
  fetchBlobUrl: async (url: string): Promise<string> => {
    const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
    if (!res.ok) throw new ApiError(res.status, `画像を受け取れませんでした（HTTP ${res.status}）`)
    return URL.createObjectURL(await res.blob())
  },

  setup: () => request<SetupStatus>('GET', '/api/setup'),
  setupDownload: (key: string) => request<SetupDownload>('POST', `/api/setup/download/${key}`),
  setupDownloads: () => request<{ downloads: SetupDownload[] }>('GET', '/api/setup/downloads'),
  detectInfo: () =>
    request<{ models: { key: string; repo: string; file: string; license: string; url: string }[] }>(
      'GET',
      '/api/detect/info',
    ),
}
