# Swap Illustration Studio のイメージ（マルチステージ）
#
# 1. node でフロントエンド（React + Vite）をビルド
# 2. python の実行イメージにバックエンドとビルド済みのフロントエンドを入れる
#
# データ（設定・検出モデル・一時ファイル。履歴は残さない）はイメージに入れず、docker-compose.yml が ./data を /app/data に
# マウントする。

# ---------------------------------------------------------------- フロントエンド
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 実行イメージ
FROM python:3.12-slim

# fonts-dejavu-core … 枠の番号バッジの数字（学習データと同じ DejaVu Sans Bold）
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY backend/app /app/backend/app
COPY --from=frontend /src/frontend/dist /app/frontend/dist

# compose は `user: <UID>:<GID>` で動かすので、任意の UID でも書ける HOME とデータの置き場を用意する
RUN mkdir -p /app/data /home/app && chmod 0777 /app/data /home/app
ENV HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    SWAP_DATA_DIR=/app/data \
    SWAP_FRONTEND_DIST=/app/frontend/dist

EXPOSE 2760
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "2760"]
