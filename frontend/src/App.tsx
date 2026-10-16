// Swap Illustration Studio の画面（PC は 3 カラム、スマホは「枠の指定」→「結果」の 2 画面）

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ApiError, api, setUnauthorizedHandler } from './api'
import CropDialog from './components/CropDialog'
import { Dialog, FileButton, Segmented, Spinner, readClipboardImage } from './components/common'
import SessionStrip from './components/SessionStrip'
import Login from './components/Login'
import { Logo } from './components/Logo'
import {
  AssignPanel,
  Badge,
  GenSettingsPanel,
  OutfitPanel,
  PromptPanel,
  RefsPanel,
  ScenePanel,
  settingsSummary,
} from './components/panels'
import ResultView from './components/ResultView'
import SceneCanvas from './components/SceneCanvas'
import SettingsDialog from './components/SettingsDialog'
import { editorReducer, initialEditor, moveItem, newId } from './lib/editor'
import { untargetedPersons } from './lib/geometry'
import { generateRequest, sceneSpec, validate, type SceneInput } from './lib/request'
import type {
  AppSettings,
  Box,
  Detection,
  FaceMode,
  GenSettings,
  Health,
  GenerateRequest,
  ImageInfo,
  Mode,
  RefImage,
  SessionJob,
  Target,
} from './types'

function useMediaQuery(q: string): boolean {
  const [m, setM] = useState(() => window.matchMedia(q).matches)
  useEffect(() => {
    const mq = window.matchMedia(q)
    const on = () => setM(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [q])
  return m
}

const DEFAULT_GEN: GenSettings = { model: 'turbo', strength: 1.0, seed: null, count: 1 }
const GEN_KEY = 'swap.gen'

function loadGen(): GenSettings {
  try {
    const raw = localStorage.getItem(GEN_KEY)
    if (raw) return { ...DEFAULT_GEN, ...JSON.parse(raw) }
  } catch {
    /* 保存なし */
  }
  return DEFAULT_GEN
}

type Auth = 'checking' | 'need' | 'ok'

export default function App() {
  const [auth, setAuth] = useState<Auth>('checking')
  useEffect(() => {
    setUnauthorizedHandler(() => setAuth('need'))
    api
      .authStatus()
      .then((s) => setAuth(s.ok ? 'ok' : 'need'))
      .catch(() => setAuth('ok')) // サーバーに繋がらないときは本画面でエラーを出す
    return () => setUnauthorizedHandler(null)
  }, [])
  if (auth === 'checking') return <div className="boot"><Spinner /></div>
  if (auth === 'need') return <Login onDone={() => setAuth('ok')} />
  return <Studio onLogout={async () => { await api.logout().catch(() => null); setAuth('need') }} />
}

function Studio({ onLogout }: { onLogout: () => void }) {
  const isPhone = useMediaQuery('(max-width: 899px)')

  // ---------------------------------------------------------------- 状態
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [scene, setScene] = useState<ImageInfo | null>(null)
  const [refs, setRefs] = useState<RefImage[]>([])
  const [editor, dispatch] = useReducer(editorReducer, initialEditor)
  const [detection, setDetection] = useState<Detection | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [mode, setMode] = useState<Mode>('marked')
  const [faceMode, setFaceMode] = useState<FaceMode>('auto')
  const [template, setTemplate] = useState(0)
  const [gen, setGenState] = useState<GenSettings>(loadGen)
  const [autoPrompt, setAutoPrompt] = useState('')
  const [promptOverride, setPromptOverride] = useState<string | null>(null)
  const [promptInfo, setPromptInfo] = useState<{ face: boolean; warnings: string[]; error: string | null; loading: boolean }>({
    face: false,
    warnings: [],
    error: null,
    loading: false,
  })
  const [drawMode, setDrawMode] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const [crop, setCrop] = useState<{ image: ImageInfo; replaceIndex: number | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [session, setSession] = useState<SessionJob[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [view, setView] = useState<'edit' | 'result'>('edit')
  const [dialog, setDialog] = useState<null | 'settings' | 'outfit' | 'gen' | 'menu' | { pickFor: number }>(null)

  const setGen = (g: GenSettings) => {
    setGenState(g)
    try {
      localStorage.setItem(GEN_KEY, JSON.stringify(g))
    } catch {
      /* 保存できなくても動く */
    }
  }
  const showError = (e: unknown) => setToast({ kind: 'error', text: e instanceof Error ? e.message : String(e) })
  const info = (text: string) => setToast({ kind: 'info', text })

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), toast.kind === 'error' ? 9000 : 3500)
    return () => window.clearTimeout(t)
  }, [toast])

  // ---------------------------------------------------------------- 初期読み込み
  const refreshHealth = useCallback(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])
  useEffect(() => {
    api.settings().then(setSettings).catch(showError)
    refreshHealth()
  }, [refreshHealth])

  // ---------------------------------------------------------------- 画像の追加
  const uploadScene = async (file: Blob) => {
    setBusy(true)
    try {
      const img = await api.uploadImage(file, (file as File).name || 'scene.png')
      setScene(img)
      setDetection(null)
      dispatch({ type: 'reset', frames: [] })
      setPromptOverride(null)
      setPreview(null)
      // 検出は自動では走らせない（初回は検出モデルのダウンロードがあるため、押したときだけ）
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }

  const addRef = async (file: Blob) => {
    if (refs.length >= 4) return showError('人物（B）は 4 人までです')
    setBusy(true)
    try {
      const img = await api.uploadImage(file, (file as File).name || 'person.png')
      setCrop({ image: img, replaceIndex: null })
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }

  const finishCrop = async (box: Box | null) => {
    if (!crop) return
    setBusy(true)
    try {
      const image = box ? await api.crop(crop.image.id, box) : crop.image
      if (crop.replaceIndex !== null) {
        setRefs((rs) => rs.map((r, i) => (i === crop.replaceIndex ? { ...r, image } : r)))
      } else {
        setRefs((rs) => {
          const next = [...rs, { key: newId('b'), image, original: crop.image }].slice(0, 4)
          // まだ B の無い枠があれば、新しい B を割り当てる
          const idx = next.length - 1
          const free = editor.frames.find((f) => f.ref === null)
          if (free) dispatch({ type: 'setRef', id: free.id, ref: idx })
          return next
        })
      }
      setCrop(null)
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }

  // Ctrl+V / ⌘+V: 画像なら A に貼る（切り抜き中は無視）
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (crop) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      const file = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/'))
      if (file) {
        e.preventDefault()
        uploadScene(file)
        info('貼り付けた画像をシーン（A）にしました')
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })

  // ---------------------------------------------------------------- 検出
  const detect = async () => {
    if (!scene) return
    setDetecting(true)
    try {
      const d = await api.detect(scene.id)
      setDetection(d)
      if (!d.available || d.message) info(d.message || '検出できませんでした')
      else info(`${d.persons.length} 人を検出しました。置き換える人をタップしてください`)
    } catch (e) {
      showError(e)
    } finally {
      setDetecting(false)
    }
  }

  const candidates = useMemo(() => {
    if (!detection) return []
    const persons = detection.persons.map((p) => p.box)
    const used = new Set(editor.frames.flatMap((f) => (f.detIndex !== null ? [f.detIndex] : [])))
    return untargetedPersons(persons, editor.frames.map((f) => f.box), 0.6)
      .filter((i) => !used.has(i))
      .map((i) => ({ index: i, box: persons[i] }))
  }, [detection, editor.frames])

  // ---------------------------------------------------------------- 指示文（自動生成）
  const input: SceneInput = { scene, frames: editor.frames, refs, detection, mode, faceMode, template }
  const spec = sceneSpec(input)
  const specKey = spec ? JSON.stringify(spec) : ''
  useEffect(() => {
    if (!specKey) {
      setAutoPrompt('')
      setPromptInfo({ face: false, warnings: [], error: null, loading: false })
      return
    }
    setPromptInfo((p) => ({ ...p, loading: true }))
    const t = window.setTimeout(() => {
      api
        .instruction(JSON.parse(specKey))
        .then((r) => {
          setAutoPrompt(r.prompt)
          setPromptInfo({ face: r.face, warnings: r.warnings, error: null, loading: false })
        })
        .catch((e) => setPromptInfo({ face: false, warnings: [], error: (e as Error).message, loading: false }))
    }, 250)
    return () => window.clearTimeout(t)
  }, [specKey])

  // 枠が変わったら送る画像のプレビューは消す
  useEffect(() => {
    setPreview((p) => {
      if (p) URL.revokeObjectURL(p)
      return null
    })
  }, [specKey])

  const togglePreview = async () => {
    if (preview) {
      URL.revokeObjectURL(preview)
      setPreview(null)
      return
    }
    if (!spec) return
    if (mode === 'position') return info('位置で指定のときは、丸なしの A をそのまま送ります')
    try {
      setPreview(await api.previewMarked(spec))
    } catch (e) {
      showError(e)
    }
  }

  // ---------------------------------------------------------------- 生成・結果（今回のセッションだけ）
  const reason = validate(input)

  const updateEntry = useCallback((id: string, fn: (e: SessionJob) => SessionJob) => {
    setSession((list) => list.map((e) => (e.job.id === id ? fn(e) : e)))
  }, [])

  /** 生成を投入して、今回の結果の一覧に足す（元の A はブラウザのメモリに取り込んでおく） */
  const submit = async (req: GenerateRequest, original: { url: string | null; size: SessionJob['size'] }) => {
    setBusy(true)
    try {
      const job = await api.generate(req)
      const originalBlob = original.url ? await api.fetchBlobUrl(original.url).catch(() => null) : null
      setSession((list) => [
        { job, results: [], inputs: {}, original: originalBlob, size: original.size, received: false, receiveError: null },
        ...list,
      ])
      setCurrentId(job.id)
      setView('result')
    } catch (e) {
      showError(e)
    } finally {
      setBusy(false)
    }
  }

  const generate = async () => {
    if (reason || !scene) return showError(reason ?? '入力が足りません')
    await submit(generateRequest(input, gen, promptOverride), {
      url: scene.url,
      size: { width: scene.width, height: scene.height },
    })
  }

  // 生成中のジョブを 1 秒ごとに取り直し、終わったら結果をブラウザに受け取ってサーバー側を消す
  const receiving = useRef(new Set<string>())
  const activeIds = session
    .filter((e) => e.job.status === 'queued' || e.job.status === 'running')
    .map((e) => e.job.id)
    .join(',')
  useEffect(() => {
    if (!activeIds) return
    const ids = activeIds.split(',')
    const t = window.setInterval(() => {
      ids.forEach((id) => {
        api
          .job(id)
          .then((j) => updateEntry(id, (e) => ({ ...e, job: j })))
          .catch((err) => {
            if (err instanceof ApiError && err.status === 404) {
              updateEntry(id, (e) => ({
                ...e,
                job: { ...e.job, status: 'error', error: 'サーバー側でジョブが見つかりません（アプリが再起動した可能性）' },
              }))
            }
          })
      })
    }, 1000)
    return () => window.clearInterval(t)
  }, [activeIds, updateEntry])

  useEffect(() => {
    session.forEach((e) => {
      const done = e.job.status === 'done' || e.job.status === 'error' || e.job.status === 'cancelled'
      if (!done || e.received || e.receiveError || receiving.current.has(e.job.id)) return
      receiving.current.add(e.job.id)
      const job = e.job
      ;(async () => {
        try {
          const results = await Promise.all(
            job.results.map(async (r) => ({ url: await api.fetchBlobUrl(r.url), seed: r.seed, elapsed: r.elapsed })),
          )
          const inputs: Record<string, string> = {}
          for (const [k, url] of Object.entries(job.inputs)) inputs[k] = await api.fetchBlobUrl(url)
          await api.discardJob(job.id).catch(() => null)
          updateEntry(job.id, (x) => ({ ...x, results, inputs, received: true }))
        } catch (err) {
          updateEntry(job.id, (x) => ({ ...x, receiveError: (err as Error).message }))
        }
      })()
    })
  }, [session, updateEntry])

  const current = session.find((e) => e.job.id === currentId) ?? null

  const rerun = async (opts: { seed: number | null; strength?: number }) => {
    if (!current) return
    const req = current.job.request
    await submit(
      { ...req, settings: { ...req.settings, seed: opts.seed, strength: opts.strength ?? current.job.settings.strength } },
      { url: null, size: current.size },
    ).then(() => {
      // 元の A は前の結果と同じものを使う
      setSession((list) => list.map((e, i) => (i === 0 && !e.original ? { ...e, original: current.original } : e)))
    })
  }

  const cancelJob = async () => {
    if (!current) return
    try {
      const j = await api.cancel(current.job.id)
      updateEntry(j.id, (e) => ({ ...e, job: j }))
    } catch (e) {
      showError(e)
    }
  }

  const openEntry = (id: string) => {
    setCurrentId(id)
    setView('result')
    setDialog(null)
  }

  const switchTarget = async (t: Target) => {
    try {
      setSettings(await api.saveSettings({ target: t }))
      refreshHealth()
    } catch (e) {
      showError(e)
    }
  }

  // B の操作
  const removeRef = (i: number) => {
    setRefs((rs) => rs.filter((_, k) => k !== i))
    dispatch({ type: 'refRemoved', index: i })
  }
  const moveRef = (from: number, to: number) => {
    if (to < 0 || to >= refs.length) return
    setRefs((rs) => moveItem(rs, from, to))
    dispatch({ type: 'refMoved', from, to })
  }
  const recrop = (i: number) => setCrop({ image: refs[i].original, replaceIndex: i })

  // ---------------------------------------------------------------- 描画部品
  const loraName = settings ? (settings.target === 'cloud' ? settings.lora_name_cloud : settings.lora_name_local) : ''
  const generateLabel = editor.frames.length ? `生成する（${editor.frames.length} 人を置き換え）` : '生成する'

  const header = (
    <header className="app-header">
      <div className="brand">
        <Logo size={isPhone ? 24 : 28} />
        <span className="brand-name">{isPhone ? 'Swap Studio' : 'Swap Illustration Studio'}</span>
      </div>
      {!isPhone && (
        <span className="pill" title={loraName}>
          LoRA: {loraName.split('/').pop()?.replace('.safetensors', '') || '—'}
        </span>
      )}
      <div className="grow" />
      {!isPhone && settings && (
        <label className="row tight small muted">
          実行先
          <select value={settings.target} onChange={(e) => switchTarget(e.target.value as Target)}>
            <option value="local">ローカルの ComfyUI</option>
            <option value="cloud">Comfy Cloud</option>
          </select>
        </label>
      )}
      {health && (
        <span
          className={`dot ${health.comfy_ok ? 'ok' : 'ng'}`}
          title={health.comfy_ok ? `接続中: ${health.comfy_url}` : health.comfy_error ?? ''}
          onClick={refreshHealth}
        />
      )}
      {isPhone ? (
        <button type="button" className="icon-btn" aria-label="メニュー" onClick={() => setDialog('menu')}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      ) : (
        <>
          <button type="button" className="btn" onClick={() => setDialog('settings')}>
            設定
          </button>
        </>
      )}
    </header>
  )

  const toolbar = (
    <div className="toolbar">
      <Segmented
        label="指定方法"
        value={mode}
        options={[
          { value: 'marked', label: '枠で指定' },
          { value: 'position', label: '位置で指定' },
        ]}
        onChange={setMode}
        small={isPhone}
      />
      {!isPhone && <span className="divider" />}
      <button type="button" className="btn" onClick={detect} disabled={!scene || detecting}>
        {detecting ? <Spinner /> : <PersonIcon />}
        {isPhone ? '自動検出' : '人物を自動検出'}
      </button>
      <button
        type="button"
        className={`btn${drawMode ? ' btn-on' : ''}`}
        onClick={() => setDrawMode((v) => !v)}
        aria-pressed={drawMode}
        disabled={!scene}
      >
        <RectIcon />
        枠を描く
      </button>
      <button type="button" className="btn" onClick={() => dispatch({ type: 'undo' })} disabled={!editor.past.length}>
        元に戻す
      </button>
      {isPhone && scene && <FileButton className="btn" label="A を変更" onFiles={(fs) => uploadScene(fs[0])} />}
      {!isPhone && (
        <button type="button" className={`btn${preview ? ' btn-on' : ''}`} onClick={togglePreview} disabled={!spec}>
          送る画像を確認
        </button>
      )}
      {!isPhone && <span className="muted small">人物をクリックで対象に追加／ドラッグで枠を描く・調整</span>}
    </div>
  )

  const canvas = scene ? (
    <SceneCanvas
      image={scene}
      frames={editor.frames}
      selected={editor.selected}
      dispatch={dispatch}
      candidates={candidates}
      drawMode={drawMode}
      refsCount={refs.length}
      maxHeight={isPhone ? '58vh' : 'calc(100vh - 330px)'}
      overlayUrl={preview}
      onLimit={() => showError('枠は 4 つまでです')}
    />
  ) : (
    <div className="canvas-empty">
      <p>差し替えたいイラスト（シーン A）を選んでください</p>
      <div className="row">
        <FileButton className="btn btn-primary" label="画像を選ぶ" onFiles={(fs) => uploadScene(fs[0])} />
        <button
          type="button"
          className="btn"
          onClick={async () => {
            try {
              const b = await readClipboardImage()
              if (b) uploadScene(b)
              else showError('クリップボードに画像がありません（Ctrl+V / ⌘+V でも貼り付けられます）')
            } catch {
              showError('クリップボードを読めませんでした')
            }
          }}
        >
          貼り付け
        </button>
      </div>
      {!isPhone && <p className="muted small">ドラッグ＆ドロップ、Ctrl+V / ⌘+V でも追加できます</p>}
    </div>
  )

  const resultView = current && (
    <ResultView
      entry={current}
      onBack={() => setView('edit')}
      onRerun={rerun}
      onCancel={cancelJob}
      busy={busy}
      maxHeight={isPhone ? '62vh' : 'calc(100vh - 380px)'}
    />
  )

  const dialogs = (
    <>
      {crop && (
        <CropDialog
          image={crop.image}
          busy={busy}
          onCancel={() => setCrop(null)}
          onCrop={(b) => finishCrop(b)}
          onUseWhole={() => finishCrop(null)}
        />
      )}
      {dialog === 'settings' && settings && (
        <SettingsDialog
          settings={settings}
          onSaved={(s) => {
            setSettings(s)
            refreshHealth()
          }}
          onClose={() => setDialog(null)}
          onLogout={onLogout}
        />
      )}
      {dialog === 'outfit' && (
        <Dialog title="服装" onClose={() => setDialog(null)}>
          <OutfitPanel frames={editor.frames} dispatch={dispatch} bare />
        </Dialog>
      )}
      {dialog === 'gen' && (
        <Dialog title="設定" onClose={() => setDialog(null)}>
          <GenSettingsPanel
            gen={gen}
            setGen={setGen}
            faceMode={faceMode}
            setFaceMode={setFaceMode}
            faceDetected={promptInfo.face}
            template={template}
            setTemplate={setTemplate}
            bare
          />
          <PromptPanel
            auto={autoPrompt}
            override={promptOverride}
            setOverride={setPromptOverride}
            warnings={promptInfo.warnings}
            loading={promptInfo.loading}
            error={promptInfo.error}
          />
        </Dialog>
      )}
      {typeof dialog === 'object' && dialog && 'pickFor' in dialog && (
        <Dialog title={`枠 ${dialog.pickFor + 1} に入れる人物`} onClose={() => setDialog(null)}>
          <RefsPanel
            refs={refs}
            frames={editor.frames}
            onAdd={addRef}
            onRecrop={recrop}
            onRemove={removeRef}
            onMove={moveRef}
            onError={showError}
            selectFor={{
              frameIndex: dialog.pickFor,
              current: editor.frames[dialog.pickFor]?.ref ?? null,
              onSelect: (i) => {
                const f = editor.frames[dialog.pickFor]
                if (f) dispatch({ type: 'setRef', id: f.id, ref: i })
                setDialog(null)
              },
            }}
          />
        </Dialog>
      )}
      {dialog === 'menu' && settings && (
        <Dialog title="メニュー" onClose={() => setDialog(null)}>
          <div className="form">
            <div className="field">
              <span className="label">実行先</span>
              <Segmented
                label="実行先"
                value={settings.target}
                options={[
                  { value: 'local', label: 'ローカル' },
                  { value: 'cloud', label: 'Comfy Cloud' },
                ]}
                onChange={switchTarget}
              />
              {health && (
                <span className={`small ${health.comfy_ok ? 'ok' : 'error'}`}>
                  {health.comfy_ok ? '接続できています' : health.comfy_error}
                </span>
              )}
            </div>
            <button type="button" className="btn block" onClick={() => setDialog('settings')}>
              設定・セットアップ
            </button>
            {current && (
              <button
                type="button"
                className="btn block"
                onClick={() => {
                  setView('result')
                  setDialog(null)
                }}
              >
                直近の結果を見る
              </button>
            )}
          </div>
        </Dialog>
      )}
      {toast && (
        <div className={`toast ${toast.kind}`} role="status" onClick={() => setToast(null)}>
          {toast.text}
        </div>
      )}
    </>
  )

  // ---------------------------------------------------------------- スマホ
  if (isPhone) {
    if (view === 'result' && current) {
      return (
        <div className="app phone">
          {resultView}
          {dialogs}
        </div>
      )
    }
    return (
      <div className="app phone">
        {header}
        <div className="phone-canvas">
          {canvas}
          {scene && (
            <p className="muted small hint-line">
              人物をタップすると枠が付きます。もう一度タップで外せます。枠の角をドラッグで大きさを調整。
            </p>
          )}
        </div>
        <section className="sheet">
          {toolbar}
          <div className="sheet-rows">
            {editor.frames.map((f, i) => (
              <div className="assign-row" key={f.id}>
                <Badge index={i} />
                <span className="arrow">→</span>
                <button type="button" className="pick-btn" onClick={() => setDialog({ pickFor: i })}>
                  {f.ref !== null && refs[f.ref] ? (
                    <>
                      <img src={refs[f.ref].image.url} alt="" />
                      <span>B{f.ref + 1}</span>
                    </>
                  ) : (
                    <span className="muted">人物（B）を選ぶ</span>
                  )}
                </button>
              </div>
            ))}
            {!editor.frames.length && (
              <div className="row between">
                <span className="muted small">
                  {scene ? '置き換える人物に枠を付けてください' : 'まずシーン（A）を選んでください'}
                </span>
                {scene && (
                  <FileButton className="btn small" label="A を変更" onFiles={(fs) => uploadScene(fs[0])} />
                )}
              </div>
            )}
            {editor.frames.length > 0 && (
              <div className="summary-row">
                <span className="muted">服装：</span>
                <span className="grow small">
                  {editor.frames.map((f, i) => (
                    <span key={f.id} className="outfit-chip">
                      {i + 1} {f.outfit === 'a' ? 'A の服装のまま' : 'B の服を着せる'}
                    </span>
                  ))}
                </span>
                <button type="button" className="link" onClick={() => setDialog('outfit')}>
                  変更
                </button>
              </div>
            )}
            <div className="summary-row">
              <span className="grow small mono">{settingsSummary(gen)}</span>
              <button type="button" className="link" onClick={() => setDialog('gen')}>
                変更
              </button>
            </div>
            {refs.length === 0 && scene && (
              <button type="button" className="btn dashed block" onClick={() => setDialog({ pickFor: 0 })}>
                ＋ 入れたい人物（B）を追加
              </button>
            )}
          </div>
          <button type="button" className="btn btn-primary block big" onClick={generate} disabled={busy || !!reason}>
            {busy ? <Spinner /> : null}
            {generateLabel}
          </button>
          {reason && scene && <p className="muted small center">{reason}</p>}
          <SessionStrip entries={session} currentId={null} onOpen={openEntry} compact />
        </section>
        {dialogs}
      </div>
    )
  }

  // ---------------------------------------------------------------- PC
  return (
    <div className="app pc">
      {header}
      <div className="columns">
        <aside className="col-left">
          <ScenePanel scene={scene} onFile={uploadScene} onError={showError} />
          <RefsPanel
            refs={refs}
            frames={editor.frames}
            onAdd={addRef}
            onRecrop={recrop}
            onRemove={removeRef}
            onMove={moveRef}
            onError={showError}
          />
        </aside>
        <main className="col-center">
          {view === 'result' && current ? (
            <section className="panel">{resultView}</section>
          ) : (
            <>
              {toolbar}
              <section className="panel canvas-panel">{canvas}</section>
              {preview && <p className="notice small">送る画像（A_marked）を表示中。学習時と同じ形の丸で描いています。</p>}
            </>
          )}
          <SessionStrip entries={session} currentId={view === 'result' ? currentId : null} onOpen={openEntry} />
        </main>
        <aside className="col-right">
          <AssignPanel frames={editor.frames} refs={refs} dispatch={dispatch} />
          <OutfitPanel frames={editor.frames} dispatch={dispatch} />
          <GenSettingsPanel
            gen={gen}
            setGen={setGen}
            faceMode={faceMode}
            setFaceMode={setFaceMode}
            faceDetected={promptInfo.face}
            template={template}
            setTemplate={setTemplate}
          />
          <PromptPanel
            auto={autoPrompt}
            override={promptOverride}
            setOverride={setPromptOverride}
            warnings={promptInfo.warnings}
            loading={promptInfo.loading}
            error={promptInfo.error}
          />
          <button type="button" className="btn btn-primary block big" onClick={generate} disabled={busy || !!reason}>
            {busy ? <Spinner /> : null}
            {generateLabel}
          </button>
          <p className="muted small">
            {reason ?? '枠付きの画像と人物の画像は、学習時と同じ形式で自動的に作られて送られます。'}
          </p>
        </aside>
      </div>
      {dialogs}
    </div>
  )
}

function PersonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="5" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M2 15c1-4 11-4 12 0" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function RectIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
    </svg>
  )
}
