// 履歴（サムネイルの帯と、すべて見るダイアログ）

import type { Job } from '../types'
import { Dialog } from './common'

function thumbOf(job: Job): string {
  return job.results[0]?.url ?? job.inputs.canvas ?? job.inputs.A
}

function statusLabel(job: Job): string | null {
  switch (job.status) {
    case 'queued':
      return '順番待ち…'
    case 'running':
      return '生成中…'
    case 'error':
      return 'エラー'
    case 'cancelled':
      return '取り消し'
    default:
      return null
  }
}

export function HistoryStrip(props: { jobs: Job[]; currentId: string | null; onOpen: (job: Job) => void; onAll: () => void }) {
  return (
    <section className="panel history-strip">
      <div className="panel-title">
        <h2>履歴</h2>
        <button type="button" className="link" onClick={props.onAll}>
          すべて見る
        </button>
      </div>
      {!props.jobs.length && <p className="muted small">生成するとここに並びます。</p>}
      <div className="strip">
        {props.jobs.slice(0, 12).map((j) => (
          <button
            key={j.id}
            type="button"
            className={`strip-item${j.id === props.currentId ? ' on' : ''}`}
            onClick={() => props.onOpen(j)}
            title={new Date(j.created_at * 1000).toLocaleString()}
          >
            <img src={thumbOf(j)} alt="" loading="lazy" />
            {statusLabel(j) && <span className={`strip-status ${j.status}`}>{statusLabel(j)}</span>}
          </button>
        ))}
      </div>
    </section>
  )
}

export function HistoryDialog(props: {
  jobs: Job[]
  onClose: () => void
  onOpen: (job: Job) => void
  onReuse: (job: Job) => void
  onDelete: (job: Job) => void
}) {
  return (
    <Dialog title="履歴" onClose={props.onClose} wide>
      {!props.jobs.length && <p className="muted">まだ履歴はありません。</p>}
      <ul className="history-list">
        {props.jobs.map((j) => (
          <li key={j.id}>
            <button type="button" className="history-thumb" onClick={() => props.onOpen(j)}>
              <img src={thumbOf(j)} alt="" loading="lazy" />
            </button>
            <div className="history-body">
              <div className="small">
                {new Date(j.created_at * 1000).toLocaleString()}
                <span className={`status-tag ${j.status}`}>{statusLabel(j) ?? `${j.results.length} 枚`}</span>
              </div>
              <div className="muted small mono">
                {j.settings.model === 'turbo' ? 'Turbo' : '通常'} ・ 強さ {j.settings.strength.toFixed(2)} ・ seed {j.settings.seed} ・{' '}
                {j.request.targets.length} 人 ・ {j.request.mode === 'marked' ? '枠' : '位置'}
              </div>
              {j.error && <div className="error small">{j.error}</div>}
              <div className="row">
                <button type="button" className="btn small" onClick={() => props.onOpen(j)}>
                  開く
                </button>
                <button type="button" className="btn small" onClick={() => props.onReuse(j)}>
                  設定を再利用
                </button>
                <button
                  type="button"
                  className="btn small danger"
                  disabled={j.status === 'queued' || j.status === 'running'}
                  onClick={() => {
                    if (window.confirm('この履歴と画像を削除しますか？')) props.onDelete(j)
                  }}
                >
                  削除
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}
