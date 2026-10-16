// アプリの設定（実行先・LoRA・API キー）と、ローカル ComfyUI のセットアップ

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AppSettings, SetupStatus, Target } from '../types'
import { Dialog, Segmented, Spinner, formatBytes } from './common'

type Tab = 'connect' | 'setup' | 'about'

export default function SettingsDialog(props: {
  settings: AppSettings
  onSaved: (s: AppSettings) => void
  onClose: () => void
  onLogout?: () => void
  initialTab?: Tab
}) {
  const [tab, setTab] = useState<Tab>(props.initialTab ?? 'connect')
  return (
    <Dialog title="設定" onClose={props.onClose} wide>
      <Segmented
        label="設定の種類"
        value={tab}
        options={[
          { value: 'connect', label: '実行先・LoRA' },
          { value: 'setup', label: 'セットアップ' },
          { value: 'about', label: 'このアプリ' },
        ]}
        onChange={setTab}
      />
      <div className="tab-body">
        {tab === 'connect' && <ConnectTab settings={props.settings} onSaved={props.onSaved} />}
        {tab === 'setup' && <SetupTab settings={props.settings} />}
        {tab === 'about' && <AboutTab onLogout={props.settings.token_required ? props.onLogout : undefined} />}
      </div>
    </Dialog>
  )
}

function ConnectTab({ settings, onSaved }: { settings: AppSettings; onSaved: (s: AppSettings) => void }) {
  const [form, setForm] = useState({
    target: settings.target,
    local_comfy_url: settings.local_comfy_url,
    lora_name_local: settings.lora_name_local,
    lora_name_cloud: settings.lora_name_cloud,
    lora_hf_repo: settings.lora_hf_repo,
    lora_sha256: settings.lora_sha256,
  })
  const [cloudKey, setCloudKey] = useState('')
  const [hfToken, setHfToken] = useState('')
  const [loras, setLoras] = useState<{ files: string[]; error: string | null } | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  const loadLoras = useCallback((target: Target) => {
    setLoras(null)
    api
      .loras(target)
      .then(setLoras)
      .catch((e) => setLoras({ files: [], error: String(e.message ?? e) }))
  }, [])
  useEffect(() => loadLoras(form.target), [form.target, loadLoras])

  const save = async (extra: Record<string, unknown> = {}) => {
    setSaving(true)
    setMsg(null)
    try {
      const body: Record<string, unknown> = { ...form, ...extra }
      if (cloudKey) body.comfy_cloud_api_key = cloudKey
      if (hfToken) body.hf_token = hfToken
      const s = await api.saveSettings(body)
      onSaved(s)
      setCloudKey('')
      setHfToken('')
      setMsg({ ok: true, text: '保存しました' })
      loadLoras(form.target)
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const loraField = form.target === 'cloud' ? 'lora_name_cloud' : 'lora_name_local'
  return (
    <div className="form">
      <div className="field">
        <span className="label">実行先</span>
        <Segmented
          label="実行先"
          value={form.target}
          options={[
            { value: 'local', label: 'ローカルの ComfyUI' },
            { value: 'cloud', label: 'Comfy Cloud' },
          ]}
          onChange={(v) => setForm({ ...form, target: v })}
        />
      </div>
      {form.target === 'local' ? (
        <label className="field">
          <span className="label">ComfyUI の URL</span>
          <input
            type="url"
            value={form.local_comfy_url}
            placeholder={settings.local_comfy_url_default}
            onChange={(e) => setForm({ ...form, local_comfy_url: e.target.value })}
          />
          <span className="muted small">空欄なら {settings.local_comfy_url_default}（.env の COMFY_URL）</span>
        </label>
      ) : (
        <label className="field">
          <span className="label">Comfy Cloud の API キー {settings.comfy_cloud_api_key_set && <span className="ok-tag">設定済み</span>}</span>
          <input
            type="password"
            autoComplete="off"
            value={cloudKey}
            placeholder={settings.comfy_cloud_api_key_set ? '変更するときだけ入力' : 'comfyui-…'}
            onChange={(e) => setCloudKey(e.target.value)}
          />
          <span className="muted small">
            data/settings.json に保存します（.env の COMFY_CLOUD_API_KEY でも可）。API の利用には Comfy Cloud の有料プランが必要です。
            {settings.comfy_cloud_api_key_set && (
              <>
                {' '}
                <button type="button" className="link" onClick={() => save({ comfy_cloud_api_key: '' })}>
                  キーを消す
                </button>
              </>
            )}
          </span>
        </label>
      )}
      <label className="field">
        <span className="label">LoRA のファイル名（{form.target === 'cloud' ? 'Comfy Cloud' : 'ローカル'}）</span>
        <input
          list="lora-files"
          value={form[loraField]}
          onChange={(e) => setForm({ ...form, [loraField]: e.target.value })}
        />
        <datalist id="lora-files">
          {loras?.files.map((f) => <option key={f} value={f} />)}
        </datalist>
        <span className="muted small">
          {loras === null
            ? 'ComfyUI の LoRA 一覧を読み込み中…'
            : loras.error
              ? `LoRA 一覧を取得できません: ${loras.error}`
              : loras.files.includes(form[loraField])
                ? 'ComfyUI に見つかりました'
                : `ComfyUI の一覧にありません（${loras.files.length} 件から選べます）`}
        </span>
      </label>
      <details className="advanced">
        <summary>ダウンロード元・トークン（セットアップ用）</summary>
        <label className="field">
          <span className="label">LoRA の Hugging Face リポジトリ</span>
          <input
            value={form.lora_hf_repo}
            placeholder={settings.lora_hf_repo_effective}
            onChange={(e) => setForm({ ...form, lora_hf_repo: e.target.value })}
          />
        </label>
        <label className="field">
          <span className="label">LoRA の SHA-256</span>
          <input
            className="mono"
            value={form.lora_sha256}
            placeholder={settings.lora_sha256_effective}
            onChange={(e) => setForm({ ...form, lora_sha256: e.target.value })}
          />
        </label>
        <label className="field">
          <span className="label">Hugging Face のトークン（任意） {settings.hf_token_set && <span className="ok-tag">設定済み</span>}</span>
          <input type="password" autoComplete="off" value={hfToken} placeholder="hf_…" onChange={(e) => setHfToken(e.target.value)} />
          <span className="muted small">
            非公開・同意が必要なリポジトリから落とすときだけ。Hugging Face のホストにだけ送ります。
            {settings.hf_token_set && (
              <>
                {' '}
                <button type="button" className="link" onClick={() => save({ hf_token: '' })}>
                  トークンを消す
                </button>
              </>
            )}
          </span>
        </label>
      </details>
      <div className="row end">
        {msg && <span className={msg.ok ? 'ok small' : 'error small'}>{msg.text}</span>}
        <button type="button" className="btn btn-primary" onClick={() => save()} disabled={saving}>
          保存
        </button>
      </div>
    </div>
  )
}

function SetupTab({ settings }: { settings: AppSettings }) {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .setup()
      .then((s) => {
        setStatus(s)
        setError(null)
      })
      .catch((e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])

  // ダウンロード中は進捗を取り直す
  const active = status?.items.some((i) => i.download && ['downloading', 'verifying'].includes(i.download.status))
  useEffect(() => {
    if (!active) return
    const t = window.setInterval(load, 1500)
    return () => window.clearInterval(t)
  }, [active, load])

  const start = async (key: string) => {
    setBusyKey(key)
    try {
      await api.setupDownload(key)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusyKey(null)
    }
  }

  if (settings.target === 'cloud') {
    return (
      <div className="form">
        <p className="notice">
          実行先が Comfy Cloud のときはセットアップは使いません。Comfy Cloud では、モデルは用意されているものを使い、LoRA は
          Comfy Cloud の Model Library の「Import」で Hugging Face から取り込みます（詳しくは README）。
        </p>
      </div>
    )
  }
  if (!status) return <div className="form">{error ? <p className="error">{error}</p> : <Spinner />}</div>
  const md = status.models_dir
  return (
    <div className="form">
      <p className="small">
        ローカルの ComfyUI に必要なモデルと LoRA があるかを確かめます。足りないものは、ボタンを押したときだけ ComfyUI の models
        フォルダへダウンロードします（途中で止まっても、もう一度押すかアプリを起動し直すと続きから再開）。
      </p>
      <div className={`notice small${status.all_ok ? ' good' : ''}`}>
        {status.all_ok ? '必要なファイルはすべて揃っています。' : '足りないファイルがあります。'}
        {status.comfy_error && <div className="error">{status.comfy_error}（ファイルの有無だけで判定しています）</div>}
        <div className="muted">
          models フォルダ:{' '}
          {md.configured ? (
            <span className="mono">
              {md.path}
              {!md.exists ? '（見つかりません）' : !md.writable ? '（書き込めません）' : ''}
            </span>
          ) : (
            '未設定（.env の COMFY_MODELS_DIR に ComfyUI の models フォルダを書くと、ダウンロードできます）'
          )}
        </div>
      </div>
      <table className="setup-table">
        <thead>
          <tr>
            <th>ファイル</th>
            <th>状態</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {status.items.map((it) => {
            const dl = it.download
            const downloading = dl && ['downloading', 'verifying'].includes(dl.status)
            return (
              <tr key={it.key}>
                <td>
                  <div className="mono small break">{it.key}</div>
                  <div className="muted small">
                    {it.used_by.map((u) => (u === 'turbo' ? 'Turbo' : '通常')).join('・')}で使用
                    {it.source.size ? ` ・ ${formatBytes(it.source.size)}` : ''}
                  </div>
                  {dl?.error && <div className="error small">{dl.error}</div>}
                  {downloading && (
                    <div className="progress small-progress">
                      <div style={{ width: dl.total ? `${(dl.received / dl.total) * 100}%` : '30%' }} />
                    </div>
                  )}
                  {downloading && (
                    <div className="muted small mono">
                      {dl.status === 'verifying' ? 'ハッシュを確認中…' : `${formatBytes(dl.received)} / ${formatBytes(dl.total)}`}
                    </div>
                  )}
                </td>
                <td className="nowrap">
                  {it.ok ? (
                    <span className="ok-tag">あり</span>
                  ) : it.file === 'size_mismatch' ? (
                    <span className="ng-tag">サイズ違い</span>
                  ) : it.file === 'partial' ? (
                    <span className="ng-tag">途中まで</span>
                  ) : (
                    <span className="ng-tag">なし</span>
                  )}
                  {it.in_comfy && <div className="muted small">ComfyUI で確認</div>}
                </td>
                <td className="nowrap">
                  {!it.ok && it.source.kind === 'url' && (
                    <button
                      type="button"
                      className="btn small"
                      disabled={!!downloading || busyKey === it.key || !md.configured}
                      onClick={() => start(it.key)}
                      title={it.source.url ?? ''}
                    >
                      {it.file === 'partial' ? '続きから' : 'ダウンロード'}
                    </button>
                  )}
                  {!it.ok && it.source.kind === 'none' && <span className="muted small">取得元が不明（設定で URL を指定）</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="muted small">
        モデルの取得元は Hugging Face の Comfy-Org/Qwen-Image-2.1、LoRA は {settings.lora_hf_repo_effective}。Qwen-Image 2.1 と LoRA
        は Qwen Research License（非商用）です。詳細は各 Hugging Face リポジトリの LICENSE / NOTICE を参照してください。
      </p>
      <div className="row end">
        <button type="button" className="btn" onClick={load}>
          再確認
        </button>
      </div>
    </div>
  )
}

function AboutTab({ onLogout }: { onLogout?: () => void }) {
  const [models, setModels] = useState<{ key: string; repo: string; license: string; url: string }[]>([])
  useEffect(() => {
    api
      .detectInfo()
      .then((r) => setModels(r.models))
      .catch(() => setModels([]))
  }, [])
  return (
    <div className="form small">
      <p>
        Swap Illustration Studio — Qwen-Image 2.1 と LoRA「anime-swap」で、イラストの人物を参照画像の人物に差し替えます。
      </p>
      <p>人物・顔の自動検出（ローカル CPU）に使うモデル:</p>
      <ul>
        {models.map((m) => (
          <li key={m.key}>
            <a href={m.url} target="_blank" rel="noreferrer">
              {m.repo}
            </a>{' '}
            （{m.license}）
          </li>
        ))}
      </ul>
      {onLogout && (
        <button type="button" className="btn" onClick={onLogout}>
          この端末からログアウト
        </button>
      )}
    </div>
  )
}
