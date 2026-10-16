#!/usr/bin/env bash
# Swap Illustration Studio を Docker なしで起動する。
#
#   ./run.sh          本番モード: フロントエンドをビルドして FastAPI から配信（http://127.0.0.1:2760）
#   ./run.sh --dev    開発モード: uvicorn --reload と vite dev（http://localhost:5173）を並行起動
#   ./run.sh --test   バックエンド（pytest）とフロントエンド（vitest・型チェック）のテスト
#
# 設定はリポジトリ直下の .env（.env.example を参照。シェルの環境変数が優先）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# .env を読む（シェルで設定済みの変数はそちらを優先）
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key:-}" ]] || export "$key=$value"
  done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$ROOT/.env")
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-2760}"
export HOST PORT
export SWAP_BIND_HOST="$HOST"
VENV="$ROOT/.venv"

MODE="${1:-}"

log() { printf '\033[36m[run]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[run]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Python -------------------------------------------------------------
if [[ ! -x "$VENV/bin/python" ]]; then
  PY="${PYTHON:-}"
  if [[ -z "$PY" ]]; then
    if command -v python3.12 >/dev/null 2>&1; then PY=python3.12; else PY=python3; fi
  fi
  command -v "$PY" >/dev/null 2>&1 || die "python が見つかりません ($PY)"
  log "venv を作成: $VENV ($PY)"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install -r "$ROOT/backend/requirements-dev.txt"
fi

# --- フロントエンド -----------------------------------------------------
need_node() { command -v npm >/dev/null 2>&1 || die "npm が見つかりません（Node.js 18 以上を入れてください）"; }
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  need_node
  log "npm install"
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund)
fi

export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$MODE" == "--test" ]]; then
  log "pytest"
  (cd "$ROOT/backend" && "$VENV/bin/python" -m pytest -q)
  log "vitest / 型チェック"
  (cd "$ROOT/frontend" && npm test && npm run typecheck)
  exit 0
fi

if [[ "$MODE" != "--dev" && ! -f "$ROOT/frontend/dist/index.html" ]]; then
  need_node
  log "npm run build"
  (cd "$ROOT/frontend" && npm run build)
fi

if [[ "$MODE" == "--dev" ]]; then
  log "開発モード: backend http://$HOST:$PORT / frontend http://localhost:5173"
  pids=()
  cleanup() { trap - INT TERM EXIT; for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
  trap cleanup INT TERM EXIT
  "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload --reload-dir "$ROOT/backend"  &
  pids+=($!)
  (cd "$ROOT/frontend" && npm run dev) &
  pids+=($!)
  wait -n
  exit $?
fi

log "http://$HOST:$PORT で起動します"
exec "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
