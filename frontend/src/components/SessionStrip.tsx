// 今回のセッションの結果（ブラウザのメモリにだけある。リロードすると消える）

import type { SessionJob } from '../types'

function statusLabel(e: SessionJob): string | null {
  switch (e.job.status) {
    case 'queued':
      return '順番待ち…'
    case 'running':
      return '生成中…'
    case 'error':
      return 'エラー'
    case 'cancelled':
      return '取り消し'
    default:
      return e.received ? null : '受け取り中…'
  }
}

export default function SessionStrip(props: {
  entries: SessionJob[]
  currentId: string | null
  onOpen: (id: string) => void
  compact?: boolean
}) {
  if (props.compact && !props.entries.length) return null
  return (
    <section className="panel history-strip">
      <div className="panel-title">
        <h2>今回の結果</h2>
        <span className="muted small">サーバーには残りません（リロードで消えます）</span>
      </div>
      {!props.entries.length && <p className="muted small">生成するとここに並びます。</p>}
      <div className="strip">
        {props.entries.map((e) => {
          const thumb = e.results[0]?.url ?? e.original
          const label = statusLabel(e)
          return (
            <button
              key={e.job.id}
              type="button"
              className={`strip-item${e.job.id === props.currentId ? ' on' : ''}`}
              onClick={() => props.onOpen(e.job.id)}
              title={new Date(e.job.created_at * 1000).toLocaleTimeString()}
            >
              {thumb && <img src={thumb} alt="" />}
              {label && <span className={`strip-status ${e.job.status}`}>{label}</span>}
            </button>
          )
        })}
      </div>
    </section>
  )
}
