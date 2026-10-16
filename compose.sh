#!/usr/bin/env bash
# docker compose の薄いラッパー。
#
#   ./compose.sh up -d --build      # 起動
#   ./compose.sh logs -f            # ログ
#   ./compose.sh down               # 停止
#
# - リポジトリの実体パスに移動してから compose を実行する
# - UID / GID をローカルユーザーに合わせて渡す（コンテナが作るファイルの所有者をそろえる）
# - ./data をローカルユーザーの持ち物として先に作る（Docker に root で作らせない）
set -euo pipefail

cd "$(readlink -f "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
mkdir -p data

# UID は bash が常に定義している読み取り専用変数なので export だけ行う
export UID 2>/dev/null || true
export GID="${GID:-$(id -g)}"

exec docker compose "$@"
