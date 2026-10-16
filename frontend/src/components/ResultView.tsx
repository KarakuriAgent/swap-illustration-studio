// 結果（比較スライダー・複数枚の切り替え・シード変更で再生成・強さ変更・保存）

import { useEffect, useState } from 'react'
import CompareSlider from './CompareSlider'
import { Spinner } from './common'
import { fitStyle } from './SceneCanvas'
import type { Job } from '../types'

export default function ResultView(props: {
  job: Job
  /** A の大きさ（比較スライダーの縦横比） */
  size: { width: number; height: number } | null
  onBack?: () => void
  onRerun: (opts: { seed: number | null; strength?: number }) => void
  onCancel: () => void
  onReuse?: () => void
  busy: boolean
  maxHeight?: string
}) {
  const { job } = props
  const [index, setIndex] = useState(0)
  const [strengthOpen, setStrengthOpen] = useState(false)
  const [strength, setStrength] = useState(job.settings.strength)
  const [size, setSize] = useState(props.size)

  useEffect(() => {
    setStrength(job.settings.strength)
    setStrengthOpen(false)
  }, [job.id, job.settings.strength])
  useEffect(() => {
    if (index >= job.results.length && job.results.length) setIndex(job.results.length - 1)
  }, [job.results.length, index])
  useEffect(() => {
    if (props.size) return setSize(props.size)
    // 履歴から開いたときは A の大きさを画像から読む
    const img = new Image()
    img.onload = () => setSize({ width: img.naturalWidth, height: img.naturalHeight })
    img.src = job.inputs.A
  }, [job.inputs.A, props.size])

  const running = job.status === 'queued' || job.status === 'running'
  const res = job.results[index]
  const total = job.settings.count

  return (
    <div className="result">
      <div className="result-head">
        {props.onBack && (
          <button type="button" className="icon-btn" onClick={props.onBack} aria-label="編集に戻る">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path d="M11 3L5 9l6 6" fill="none" stroke="#16181C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        <span className="result-title">結果</span>
        <span className="muted small mono">
          {job.results.length ? `${index + 1} / ${total} 枚` : `0 / ${total} 枚`}
        </span>
      </div>

      {running && (
        <div className="progress-box">
          <div className="row between">
            <span className="row tight">
              <Spinner />
              {job.status === 'queued' ? '順番待ち…' : job.message || '生成中…'}
            </span>
            <button type="button" className="btn small" onClick={props.onCancel}>
              取り消す
            </button>
          </div>
          <div className="progress">
            <div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
          </div>
        </div>
      )}
      {job.status === 'error' && (
        <div className="error-box">
          <strong>生成できませんでした</strong>
          <p>{job.error}</p>
        </div>
      )}
      {job.status === 'cancelled' && <div className="notice">取り消しました。</div>}

      {res && size ? (
        <CompareSlider result={res.url} original={job.inputs.A} width={size.width} height={size.height} maxHeight={props.maxHeight} />
      ) : (
        <div className="result-placeholder" style={size ? fitStyle(size.width, size.height, props.maxHeight) : undefined}>
          <img src={job.inputs.canvas} alt="送った画像" />
          {running && <div className="placeholder-cover">生成中…</div>}
        </div>
      )}
      {res && <p className="muted small center">境目を左右にドラッグして、元の画像と見比べられます。</p>}

      <div className="result-thumbs">
        {job.results.map((r, i) => (
          <button
            key={r.file}
            type="button"
            className={`thumb${i === index ? ' on' : ''}`}
            onClick={() => setIndex(i)}
            aria-label={`${i + 1}枚目${i === index ? '（表示中）' : ''}`}
          >
            <img src={r.url} alt="" />
          </button>
        ))}
        {Array.from({ length: Math.max(0, total - job.results.length) }).map((_, i) => (
          <span key={`p${i}`} className="thumb pending" />
        ))}
        <div className="result-meta mono small">
          {res ? (
            <>
              <span>
                seed {res.seed} ・ strength {job.settings.strength.toFixed(2)}
              </span>
              <span className="muted">
                {job.settings.model === 'turbo' ? 'Turbo' : '通常'} ・ {Math.round(res.elapsed)} 秒 ・{' '}
                {job.settings.target === 'cloud' ? 'Comfy Cloud' : 'ローカル'}
              </span>
            </>
          ) : (
            <span>
              seed {job.settings.seed} ・ strength {job.settings.strength.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {strengthOpen && (
        <div className="panel inset">
          <label className="field">
            <span className="label row between">
              <span>LoRA の強さ</span>
              <span className="mono">{strength.toFixed(2)}</span>
            </span>
            <input type="range" min={0} max={1.5} step={0.05} value={strength} onChange={(e) => setStrength(Number(e.target.value))} />
          </label>
          <div className="row">
            <button type="button" className="btn grow" onClick={() => setStrengthOpen(false)}>
              やめる
            </button>
            <button
              type="button"
              className="btn btn-primary grow"
              disabled={props.busy}
              onClick={() => props.onRerun({ seed: res?.seed ?? job.settings.seed, strength })}
            >
              同じシードで再生成
            </button>
          </div>
        </div>
      )}

      <div className="result-actions">
        <div className="row">
          <button type="button" className="btn grow" disabled={props.busy} onClick={() => props.onRerun({ seed: null })}>
            シードを変えて再生成
          </button>
          <button type="button" className="btn grow" onClick={() => setStrengthOpen((v) => !v)}>
            強さを変える
          </button>
        </div>
        {res ? (
          <a className="btn btn-primary block" href={`${res.url}?download=1`} download>
            保存する
          </a>
        ) : (
          <button type="button" className="btn btn-primary block" disabled>
            保存する
          </button>
        )}
        {props.onReuse && (
          <button type="button" className="btn block" onClick={props.onReuse}>
            この設定で編集する
          </button>
        )}
      </div>
      <details className="prompt-used">
        <summary className="small">送った指示文と画像</summary>
        <p className="mono small">{job.prompt}</p>
        <div className="row wrap">
          {Object.entries(job.inputs)
            .filter(([k]) => k !== 'A')
            .map(([k, url]) => (
              <a key={k} href={url} target="_blank" rel="noreferrer" className="input-thumb">
                <img src={url} alt={k} />
                <span className="small">{k === 'canvas' ? 'image1' : k}</span>
              </a>
            ))}
        </div>
      </details>
    </div>
  )
}
