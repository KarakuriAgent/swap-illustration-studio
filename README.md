# Swap Illustration Studio

イラストの中の人物を、別の画像の人物に差し替える PWA です（PC・スマホ対応）。
Qwen-Image 2.1 と LoRA [Kohei-Yamashita/swap-illustration-lora](https://huggingface.co/Kohei-Yamashita/swap-illustration-lora) を使い、生成はローカルの ComfyUI か Comfy Cloud で行います。
LoRA のライセンスは上記リポジトリを参照してください。

## 必要なもの

- Docker（または Python 3.12 と Node.js 18 以上）
- ローカルの ComfyUI、または Comfy Cloud の API キー

## 起動

```bash
cp .env.example .env
./compose.sh up -d --build    # http://127.0.0.1:2760
```

Docker を使わない場合は `./run.sh`（初回は依存の導入とビルドも行います）。

Docker からは `http://host.docker.internal:8188` のローカル ComfyUI に接続します。ComfyUI は `--listen 0.0.0.0` などで起動してください。

## 初回セットアップ（ローカル ComfyUI）

`.env` の `COMFY_MODELS_DIR` に ComfyUI の models フォルダを書いて起動し、画面の **設定 → セットアップ** で不足しているモデルと LoRA をダウンロードします（途中で止まっても続きから再開します）。

## 使い方

1. シーン（A）を読み込む（ファイル選択・ドラッグ＆ドロップ・貼り付け）
2. 入れたい人物（B）を追加する（最大 4 人。設定画などから 1 人を切り抜けます）
3. A の上で置き換える人物に枠を付ける（「人物を自動検出」→ タップ、またはドラッグで描く）。「位置で指定」も選べます
4. 枠ごとに B と服装（B の服／A の服装のまま）を選んで「生成する」
5. 元の画像と見比べて「保存する」でダウンロード

指示文と枠付きの画像は、LoRA の学習時と同じ形式で自動的に作られます。

## スマホから使う

`.env` で `HOST=0.0.0.0` と `ACCESS_TOKEN`（16 文字以上）を設定し、`http://<PC の IP>:2760` を開いて初回にトークンを入力します。
ホーム画面に追加して PWA として使うには https が必要です。[Tailscale Serve](https://tailscale.com/kb/1312/serve)（`tailscale serve --bg 2760`）などを使い、その場合は `REQUIRE_TOKEN=1` も設定してください。

## Comfy Cloud を使う場合

- 設定画面で実行先を Comfy Cloud にし、API キーを入れます（API の利用には有料プランが必要）
- LoRA は Comfy Cloud の Model Library →「Import」で、Hugging Face の URL（`…/resolve/main/anime-swap.safetensors`）から取り込みます
- Comfy Cloud での生成は未検証です（Cloud 側のモデル・ノードの有無を確認していません）

## 主な設定（.env）

| 変数 | 既定 | 内容 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `2760` | 待ち受け |
| `ACCESS_TOKEN` | なし | `HOST` が 127.0.0.1 以外のとき必須 |
| `REQUIRE_TOKEN` | なし | `1` で常にトークンを要求 |
| `COMFY_URL` / `DOCKER_COMFY_URL` | `http://127.0.0.1:8188` / `http://host.docker.internal:8188` | ローカル ComfyUI（`./run.sh` / Docker） |
| `COMFY_MODELS_DIR` | なし | ComfyUI の models フォルダ（セットアップ用） |
| `COMFY_CLOUD_API_KEY` | なし | Comfy Cloud の API キー（画面からも設定可） |
| `HF_TOKEN` | なし | Hugging Face のトークン（任意） |

## データの扱い

入力画像と結果はアプリ内に残しません（一時ファイルは受け取り後・期限切れ・再起動時に削除）。必要な結果は「保存する」でダウンロードしてください。ComfyUI 側（output / input / 履歴）には ComfyUI の通常の動作どおり残ります。

## 開発

`./run.sh --dev`（バックエンド＋ vite dev）、`./run.sh --test`（pytest・vitest・型チェック）。

## ライセンス

アプリは [MIT](LICENSE)。LoRA と Qwen-Image 2.1 はそれぞれのリポジトリのライセンス（Qwen Research License、非商用）に従います。
