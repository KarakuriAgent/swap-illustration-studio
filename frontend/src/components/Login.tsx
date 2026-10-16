// アクセストークンの入力（LAN 越しに使うとき。トークンは HttpOnly の Cookie に保存される）

import { useState } from 'react'
import { api } from '../api'
import { Logo } from './Logo'

export default function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="login">
      <form
        className="panel login-card"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError(null)
          try {
            await api.login(token)
            onDone()
          } catch (err) {
            setError((err as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="row tight">
          <Logo />
          <strong>Swap Illustration Studio</strong>
        </div>
        <p className="small">アクセストークンを入力してください（サーバーの .env の ACCESS_TOKEN）。この端末に保存されます。</p>
        <input type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />
        {error && <p className="error small">{error}</p>}
        <button type="submit" className="btn btn-primary block" disabled={!token || busy}>
          はじめる
        </button>
      </form>
    </div>
  )
}
