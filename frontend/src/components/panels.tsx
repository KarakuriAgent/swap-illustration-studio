// 編集画面のパネル（PC では左右のカラム、スマホではシート・ダイアログの中で使う）

import { useState } from 'react'
import type { Dispatch } from 'react'
import { readClipboardImage, FileButton, DropZone, Segmented } from './common'
import type { EditorAction } from '../lib/editor'
import { frameColor } from '../lib/geometry'
import { randomSeed } from '../lib/request'
import type { FaceMode, Frame, GenSettings, ImageInfo, RefImage } from '../types'

export function Badge({ index, size = 26 }: { index: number; size?: number }) {
  return (
    <span className="badge" style={{ background: frameColor(index), width: size, height: size, fontSize: size * 0.5 }}>
      {index + 1}
    </span>
  )
}

// --------------------------------------------------------------------------- A
export function ScenePanel(props: {
  scene: ImageInfo | null
  onFile: (f: Blob) => void
  onError: (msg: string) => void
}) {
  const paste = async () => {
    try {
      const blob = await readClipboardImage()
      if (blob) props.onFile(blob)
      else props.onError('クリップボードに画像がありません（このブラウザでは Ctrl+V / ⌘+V で貼り付けてください）')
    } catch {
      props.onError('クリップボードを読めませんでした。Ctrl+V / ⌘+V で貼り付けてください')
    }
  }
  return (
    <section className="panel">
      <h2>シーン（A）</h2>
      <DropZone className="scene-thumb" onFiles={(fs) => props.onFile(fs[0])}>
        {props.scene ? (
          <img src={props.scene.url} alt="シーン A" />
        ) : (
          <div className="empty">ここに画像をドロップ／貼り付け</div>
        )}
      </DropZone>
      <div className="row">
        <FileButton className="btn grow" label={props.scene ? '画像を変更' : '画像を選ぶ'} onFiles={(fs) => props.onFile(fs[0])} />
        <button type="button" className="btn grow" onClick={paste}>
          貼り付け
        </button>
      </div>
    </section>
  )
}

// --------------------------------------------------------------------------- B
export function RefsPanel(props: {
  refs: RefImage[]
  frames: Frame[]
  onAdd: (f: Blob) => void
  onRecrop: (index: number) => void
  onRemove: (index: number) => void
  onMove: (from: number, to: number) => void
  onError: (msg: string) => void
  /** 選択モード（スマホで枠に B を割り当てるとき） */
  selectFor?: { frameIndex: number; current: number | null; onSelect: (i: number) => void }
}) {
  const full = props.refs.length >= 4
  const paste = async () => {
    try {
      const blob = await readClipboardImage()
      if (blob) props.onAdd(blob)
      else props.onError('クリップボードに画像がありません')
    } catch {
      props.onError('クリップボードを読めませんでした')
    }
  }
  return (
    <section className="panel">
      <div className="panel-title">
        <h2>入れたい人物（B）</h2>
        <span className="muted small">1枚に1人・最大4人</span>
      </div>
      <DropZone className="refs" onFiles={(fs) => fs.slice(0, 4 - props.refs.length).forEach(props.onAdd)}>
        {props.refs.map((r, i) => {
          const assigned = props.frames.flatMap((f, k) => (f.ref === i ? [k] : []))
          const selected = props.selectFor?.current === i
          return (
            <div
              key={r.key}
              className={`ref-item${selected ? ' selected' : ''}`}
              style={{ borderColor: assigned.length ? frameColor(assigned[0]) : undefined }}
            >
              <button
                type="button"
                className="ref-thumb"
                onClick={() => props.selectFor?.onSelect(i)}
                disabled={!props.selectFor}
                aria-label={`B${i + 1} を選ぶ`}
              >
                <img src={r.image.url} alt={`B${i + 1}`} />
              </button>
              <div className="ref-body">
                <span className="ref-name">B{i + 1}</span>
                <span className="muted small">
                  {assigned.length ? `枠 ${assigned.map((k) => k + 1).join('・')} に割り当て` : '未割り当て'}
                </span>
                <div className="ref-actions">
                  <button type="button" className="mini" onClick={() => props.onMove(i, i - 1)} disabled={i === 0} aria-label="上へ">
                    ↑
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => props.onMove(i, i + 1)}
                    disabled={i === props.refs.length - 1}
                    aria-label="下へ"
                  >
                    ↓
                  </button>
                  <button type="button" className="mini" onClick={() => props.onRecrop(i)}>
                    切り抜き
                  </button>
                  <button type="button" className="mini danger" onClick={() => props.onRemove(i)}>
                    削除
                  </button>
                </div>
              </div>
              {assigned.length > 0 && <Badge index={assigned[0]} />}
              {props.selectFor && (
                <button type="button" className={`btn${selected ? ' btn-primary' : ''} pick`} onClick={() => props.selectFor!.onSelect(i)}>
                  {selected ? '選択中' : 'これにする'}
                </button>
              )}
            </div>
          )
        })}
        {!full && (
          <div className="row">
            <FileButton className="btn dashed grow" label="＋ 人物を追加（画像・設定画から切り抜き）" onFiles={(fs) => fs.slice(0, 4 - props.refs.length).forEach(props.onAdd)} multiple />
            <button type="button" className="btn" onClick={paste} title="クリップボードの画像を追加">
              貼り付け
            </button>
          </div>
        )}
      </DropZone>
    </section>
  )
}

// --------------------------------------------------------------------------- 枠 → B
export function AssignPanel(props: { frames: Frame[]; refs: RefImage[]; dispatch: Dispatch<EditorAction> }) {
  return (
    <section className="panel">
      <h2>置き換え</h2>
      {!props.frames.length && <p className="muted small">A の上で、置き換える人物に枠を付けてください。</p>}
      {props.frames.map((f, i) => (
        <div className="assign-row" key={f.id}>
          <Badge index={i} />
          <span className="arrow">→</span>
          <label className="grow">
            <span className="sr-only">枠{i + 1}に入れる人物</span>
            <select
              value={f.ref ?? ''}
              onChange={(e) => props.dispatch({ type: 'setRef', id: f.id, ref: e.target.value === '' ? null : Number(e.target.value) })}
            >
              <option value="">（人物を選ぶ）</option>
              {props.refs.map((_r, k) => (
                <option key={k} value={k}>
                  B{k + 1}
                </option>
              ))}
            </select>
          </label>
          {f.ref !== null && props.refs[f.ref] && <img className="assign-thumb" src={props.refs[f.ref].image.url} alt="" />}
        </div>
      ))}
    </section>
  )
}

// --------------------------------------------------------------------------- 服装
export function OutfitPanel(props: { frames: Frame[]; dispatch: Dispatch<EditorAction>; bare?: boolean }) {
  const body = (
    <>
      {props.frames.map((f, i) => (
        <div className="outfit-row" key={f.id}>
          <div className="row tight">
            <Badge index={i} size={22} />
            <span>枠 {i + 1} の人物</span>
          </div>
          <Segmented
            label={`枠${i + 1}の服装`}
            value={f.outfit}
            options={[
              { value: 'b', label: 'B の服を着せる' },
              { value: 'a', label: 'A の服装のまま' },
            ]}
            onChange={(v) => props.dispatch({ type: 'setOutfit', id: f.id, outfit: v })}
            small
          />
        </div>
      ))}
      {!props.frames.length && <p className="muted small">枠を付けると、枠ごとに服装を選べます。</p>}
      <label className="check disabled" title="準備中">
        <input type="checkbox" disabled checked={false} readOnly />
        <span>任意：Grok で A の服装を読み取り、指示文に具体的に書き足す（「A の服装のまま」の枠だけ）〔準備中〕</span>
      </label>
    </>
  )
  if (props.bare) return body
  return (
    <section className="panel">
      <h2>服装</h2>
      {body}
    </section>
  )
}

// --------------------------------------------------------------------------- 設定
export function GenSettingsPanel(props: {
  gen: GenSettings
  setGen: (g: GenSettings) => void
  faceMode: FaceMode
  setFaceMode: (m: FaceMode) => void
  faceDetected: boolean
  template: number
  setTemplate: (t: number) => void
  bare?: boolean
}) {
  const { gen, setGen } = props
  const [seedText, setSeedText] = useState<string | null>(null)
  const body = (
    <>
      <div className="field">
        <span className="label">モデル</span>
        <Segmented
          label="モデル"
          value={gen.model}
          options={[
            { value: 'turbo', label: 'Turbo（8 steps）' },
            { value: 'base', label: '通常（25 steps）' },
          ]}
          onChange={(v) => setGen({ ...gen, model: v })}
          small
        />
      </div>
      <label className="field">
        <span className="label row between">
          <span>LoRA の強さ</span>
          <span className="mono">{gen.strength.toFixed(2)}</span>
        </span>
        <input
          type="range"
          min={0}
          max={1.5}
          step={0.05}
          value={gen.strength}
          onChange={(e) => setGen({ ...gen, strength: Number(e.target.value) })}
        />
      </label>
      <div className="row">
        <label className="field grow">
          <span className="label">シード</span>
          <div className="row tight">
            <input
              className="mono"
              type="text"
              inputMode="numeric"
              placeholder="ランダム"
              value={seedText ?? (gen.seed === null ? '' : String(gen.seed))}
              onChange={(e) => {
                const t = e.target.value.replace(/[^0-9]/g, '')
                setSeedText(t)
                setGen({ ...gen, seed: t === '' ? null : Math.min(Number(t), 2 ** 53) })
              }}
              onBlur={() => setSeedText(null)}
            />
            <button
              type="button"
              className="btn"
              title="ランダムに決める"
              onClick={() => {
                setSeedText(null)
                setGen({ ...gen, seed: randomSeed() })
              }}
            >
              ランダム
            </button>
          </div>
        </label>
        <label className="field">
          <span className="label">枚数</span>
          <select value={gen.count} onChange={(e) => setGen({ ...gen, count: Number(e.target.value) })}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted small">
        シードが空ならランダム。2 枚以上はシードを +1 ずつ変えて生成します。
      </p>
      <details className="advanced">
        <summary>詳しい設定</summary>
        <div className="field">
          <span className="label">顔アップ用の文面</span>
          <Segmented
            label="顔アップ"
            value={props.faceMode}
            options={[
              { value: 'auto', label: `自動${props.faceMode === 'auto' ? (props.faceDetected ? '（顔アップ）' : '（通常）') : ''}` },
              { value: 'on', label: '顔アップ' },
              { value: 'off', label: '通常' },
            ]}
            onChange={props.setFaceMode}
            small
          />
        </div>
        <label className="field">
          <span className="label">指示文の構文（学習時の言い回し）</span>
          <select value={props.template} onChange={(e) => props.setTemplate(Number(e.target.value))}>
            <option value={0}>基本形（おすすめ）</option>
            <option value={1}>言い回し 2</option>
            <option value={2}>言い回し 3</option>
            <option value={3}>言い回し 4（丸ありのみ）</option>
          </select>
        </label>
      </details>
    </>
  )
  if (props.bare) return body
  return (
    <section className="panel">
      <h2>設定</h2>
      {body}
    </section>
  )
}

export function settingsSummary(gen: GenSettings): string {
  return `${gen.model === 'turbo' ? 'Turbo' : '通常'}・強さ ${gen.strength.toFixed(2)}・${gen.count}枚・シード ${gen.seed ?? 'ランダム'}`
}

// --------------------------------------------------------------------------- 指示文
export function PromptPanel(props: {
  auto: string
  override: string | null
  setOverride: (v: string | null) => void
  warnings: string[]
  loading: boolean
  error: string | null
}) {
  const edited = props.override !== null
  return (
    <details className="panel prompt-panel">
      <summary>
        指示文（{edited ? '手動で編集中' : '自動生成'}・英語）{props.loading && <span className="muted small">　更新中…</span>}
      </summary>
      {edited && (
        <p className="notice small">
          編集したので自動生成を止めています（枠や服装を変えても文は変わりません）。
          <button type="button" className="link" onClick={() => props.setOverride(null)}>
            自動生成に戻す
          </button>
        </p>
      )}
      <textarea
        className="mono"
        rows={9}
        value={props.override ?? props.auto}
        placeholder="枠を付けると自動で作られます"
        onChange={(e) => props.setOverride(e.target.value)}
      />
      {props.error && <p className="error small">{props.error}</p>}
      {props.warnings.map((w) => (
        <p key={w} className="notice small">
          {w}
        </p>
      ))}
    </details>
  )
}
