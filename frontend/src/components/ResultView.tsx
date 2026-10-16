// 結果（比較スライダー・複数枚の切り替え・シード変更で再生成・強さ変更・保存）
//
// 履歴は残さないので、結果はブラウザのメモリ（blob: URL）にだけある。保存は「保存する」でダウンロード。

import { useEffect, useState } from 'react'
import CompareSlider from './CompareSlider'
import { Spinner } from './common'
import { fitStyle } from './SceneCanvas'
import type { SessionJob } from '../types'

export default function ResultView(props: {
  entry: SessionJob
  onBack?: () => void
  onRerun: (opts: { seed: number | null; strength?: number }) => void
  onCancel: () => void
  busy: boolean
  maxHeight?: string
}) {
  const { entry } = props
  const { job } = entry
  const [index, setIndex] = useState(0)
  const [strengthOpen, setStrengthOpen] = useState(false)
  const [strength, setStrength] = useState(job.settings.strength)

  useEffect(() => {
    setStrength(job.settings.strength)
    setStrengthOpen(false)
    setIndex(0)
  }, [job.id, job.settings.strength])
  useEffect(() => {
    if (index >= entry.results.length && entry.results.length) setIndex(entry.results.length - 1)
  }, [entry.results.length, index])

  const running = job.status === 'queued' || job.status === 'running'
  const receiving = !running && !entry.received && !entry.receiveError
  const res = entry.results[index]
  const total = job.settings.count
  const size = entry.size

  return (
    <div className="result">
      <div className="result-head">
        {props.onBack && (
          <button type="button" className="icon-btn" onClick={props.onBack} aria-label="編集に戻る">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path d="M11 3L5 9l6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        <span className="result-title">結果</span>
        <span className="muted small mono">{`${entry.results.length ? index + 1 : 0} / ${total} 枚`}</span>
      </div>

      {(running || receiving) && (
        <div className="progress-box">
          <div className="row between">
            <span className="row tight">
              <Spinner />
              {receiving ? '結果を受け取り中…' : job.status === 'queued' ? '順番待ち…' : job.message || '生成中…'}
            </span>
            {running && (
              <button type="button" className="btn small" onClick={props.onCancel}>
                取り消す
              </button>
            )}
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
      {entry.receiveError && (
        <div className="error-box">
          <strong>結果を受け取れませんでした</strong>
          <p>{entry.receiveError}</p>
        </div>
      )}
      {job.status === 'cancelled' && <div className="notice">取り消しました。</div>}

      {res && size && entry.original ? (
        <CompareSlider result={res.url} original={entry.original} width={size.width} height={size.height} maxHeight={props.maxHeight} />
      ) : (
        <div className="result-placeholder" style={size ? fitStyle(size.width, size.height, props.maxHeight) : undefined}>
          {entry.original && <img src={entry.original} alt="元の画像" />}
          {running && <div className="placeholder-cover">生成中…</div>}
        </div>
      )}
      {res && <p className="muted small center">境目を左右にドラッグして、元の画像と見比べられます。</p>}

      <div className="result-thumbs">
        {entry.results.map((r, i) => (
          <button
            key={r.url}
            type="button"
            className={`thumb${i === index ? ' on' : ''}`}
            onClick={() => setIndex(i)}
            aria-label={`${i + 1}枚目${i === index ? '（表示中）' : ''}`}
          >
            <img src={r.url} alt="" />
          </button>
        ))}
        {Array.from({ length: Math.max(0, total - entry.results.length) }).map((_, i) => (
          <span key={`p${i}`} className="thumb pending" />
        ))}
        <div className="result-meta mono small">
          <span>
            seed {res?.seed ?? job.settings.seed} ・ strength {job.settings.strength.toFixed(2)}
          </span>
          <span className="muted">
            {job.settings.model === 'turbo' ? 'Turbo' : '通常'}
            {res ? ` ・ ${Math.round(res.elapsed)} 秒` : ''} ・ {job.settings.target === 'cloud' ? 'Comfy Cloud' : 'ローカル'}
          </span>
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
          <a className="btn btn-primary block" href={res.url} download={`swap_seed${res.seed}.png`}>
            保存する
          </a>
        ) : (
          <button type="button" className="btn btn-primary block" disabled>
            保存する
          </button>
        )}
        <p className="muted small center">結果はサーバーに残りません。残したい画像は「保存する」でダウンロードしてください。</p>
      </div>
      <details className="prompt-used">
        <summary className="small">送った指示文と画像</summary>
        <p className="mono small">{job.prompt}</p>
        <div className="row wrap">
          {Object.entries(entry.inputs).map(([k, url]) => (
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
