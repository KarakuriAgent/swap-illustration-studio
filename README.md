# Swap Illustration Studio

イラストの人物を、参照画像の人物に差し替える PWA です。Qwen-Image 2.1 の画像編集と、そのための LoRA
「anime-swap」（[Kohei-Yamashita/swap-illustration-lora](https://huggingface.co/Kohei-Yamashita/swap-illustration-lora)）を使います。
PC でもスマホでも使え、生成は **ローカルの ComfyUI** または **Comfy Cloud** で行います。

- シーン A の上で、置き換える人物に枠（1=赤・2=青・3=緑・4=橙）を付け、枠ごとに入れたい人物 B を割り当てる
- 枠は手で描くか、「人物を自動検出」（ローカル CPU）の候補をタップして付ける
- 送る画像（A_marked）と英語の指示文は、**LoRA の学習データと同じ形式**でサーバー側が自動で作る
- 枠ごとに「B の服を着せる」／「A の服装のまま」を選べる
- 結果は元の画像と左右ドラッグで見比べ、シードや強さを変えて再生成、「保存する」でダウンロード
- **履歴は残しません**。入力も結果もサーバーには残らず、画面には今回のセッションの結果だけが出ます（後述）
- 画面はダークテーマ（暗いグレーのパネル、明るいメインボタン、色は枠だけ）

LoRA と Qwen-Image 2.1 のライセンス（Qwen Research License、非商用）は
[LoRA の Hugging Face リポジトリ](https://huggingface.co/Kohei-Yamashita/swap-illustration-lora) の LICENSE / NOTICE を参照してください。

---

## 起動

### Docker（おすすめ）

```bash
cp .env.example .env          # 必要なら編集（ポート・ComfyUI の models フォルダなど）
./compose.sh up -d --build    # http://127.0.0.1:2760
./compose.sh logs -f          # ログ
./compose.sh down             # 停止
```

- `./data` には設定・セットアップの状況・検出モデルと、一時ファイル（`data/tmp`、起動時と期限切れで消える）だけを置きます。
- ローカルの ComfyUI には `http://host.docker.internal:8188`（ホストの ComfyUI）でつなぎます。ComfyUI が `127.0.0.1` だけで
  待ち受けているとコンテナから届かないので、`--listen 0.0.0.0` などで起動してください（別の URL なら `.env` の `DOCKER_COMFY_URL`）。
- `compose.sh` は `docker compose` の薄いラッパーで、ローカルユーザーの UID/GID を渡し、`./data` を先に作ります。

### Docker なし

Python 3.12 と Node.js 18 以上が必要です。

```bash
./run.sh          # 初回は venv 作成・npm install・ビルドまで行い、http://127.0.0.1:2760 で起動
./run.sh --dev    # 開発: uvicorn --reload（:2760）と vite dev（:5173）
./run.sh --test   # テスト（pytest・vitest・型チェック）
```

---

## 使い方

**PC**（3 カラム）

1. 左：「シーン（A）」に差し替えたいイラストを入れる（ファイル選択・ドラッグ＆ドロップ・Ctrl+V / ⌘+V・「貼り付け」）
2. 左：「入れたい人物（B）」を追加（最大 4 人）。追加すると切り抜きツールが開くので、設定画などから 1 人の全身・バストアップを
   矩形で切り出す（「切り抜かずに使う」も可）。↑↓ で並べ替え、「切り抜き」でやり直し
3. 中央：A の上で置き換える人物に枠を付ける
   - 何もないところをドラッグ → 枠を描く。枠をクリック → 選択（角のハンドルで大きさ、ドラッグで移動）。選択中の枠をもう一度クリック、
     または × で外す。「元に戻す」で 1 手戻る
   - 「人物を自動検出」→ 人物の候補が点線で出るので、クリックで枠にする
   - 「枠で指定」（丸あり、既定）／「位置で指定」（丸なし。枠の中心の左右順から the person on the left などの言葉を作る）
   - 「送る画像を確認」で、実際に送る A_marked（学習時と同じ形の丸）を表示
4. 右：枠ごとに入れる B、服装、設定（Turbo / 通常・LoRA の強さ 0〜1.5・シード・枚数 1〜4）を選ぶ。指示文（英語）は自動で作られ、
   開いて編集もできる（編集すると自動生成は止まる。「自動生成に戻す」で戻る）
5. 「生成する」。結果は中央に表示（比較スライダー・複数枚の切り替え・シードを変えて再生成・強さを変える・保存）。
   中央下の「今回の結果」から、このセッションで作った結果を開き直せます（リロードすると消えます）

**スマホ**（「枠の指定」→「結果」の 2 画面）

- 画像の上で人物をタップすると枠が付き、もう一度タップで外れます。角をドラッグで大きさを調整
- 下のシートで、枠 → B（タップで B の選択・追加・切り抜き）、服装（変更）、設定（1 行の要約 → 変更）、生成
- 結果画面で左右ドラッグの比較、シード変更で再生成、強さ変更、保存
- 右上のメニューから実行先の切り替え・設定・直近の結果

---

## スマホで使う

### LAN 内で使う

`.env` で待ち受けを LAN に開き、アクセストークンを設定します（**トークンが無いと起動しません**）。

```bash
HOST=0.0.0.0
ACCESS_TOKEN=（16 文字以上のランダムな文字列。例: openssl rand -hex 24 の出力）
```

スマホのブラウザで `http://<PC の IP アドレス>:2760` を開き、初回にトークンを入力します（HttpOnly の Cookie に保存）。

ただし **service worker（PWA のインストール・全画面起動）は https か localhost でしか動きません**。`http://192.168.x.x` では
ブラウザのタブとしては使えますが、「ホーム画面に追加」しても PWA としては動かない（ブラウザによってはただのブックマークになる）ことがあります。

### https で使う（PWA としてホーム画面に追加する）

どちらもアプリは `127.0.0.1` で待ち受けたまま、外からの入口だけを https にします。外から届くので `REQUIRE_TOKEN=1` と
`ACCESS_TOKEN` を設定してください。

- **Tailscale**（自分の端末だけで使うならこれが簡単）
  1. PC とスマホに Tailscale を入れて同じ tailnet にログイン
  2. 管理画面で MagicDNS と HTTPS 証明書を有効にする
  3. PC で `tailscale serve --bg 2760` → `https://<マシン名>.<tailnet>.ts.net/` で開ける（tailnet の外には公開されない）
- **Cloudflare Tunnel**（独自ドメインがある場合）
  1. `cloudflared tunnel create swap-studio` → DNS に `swap.example.com` を割り当て
  2. 設定で `service: http://127.0.0.1:2760` を指定して `cloudflared tunnel run`
  3. インターネットに公開されるので、トークンに加えて Cloudflare Access などで入口を絞ることをおすすめします

スマホで https の URL を開き、iOS は共有 →「ホーム画面に追加」、Android は「アプリをインストール」で全画面のアプリとして使えます。

---

## ローカル ComfyUI のセットアップ

画面の **設定 → セットアップ** で、必要なファイルが揃っているかを確認し、足りないものをダウンロードできます。

- 必要なファイルは同梱のワークフロー（`backend/app/workflows/`）のローダーから自動で列挙します:
  `diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors`（Turbo）、`diffusion_models/qwen_image_2.1_int8_convrot.safetensors`（通常）、
  `text_encoders/qwen3vl_8b_int8_convrot.safetensors`、`vae/qwen_image_2.1_vae_bf16.safetensors`、`loras/qwen-image-21/anime-swap.safetensors`
- ComfyUI の `/object_info` に見えているか、`COMFY_MODELS_DIR` の正しいサブフォルダにファイルがあれば「あり」です
- ダウンロードするには `.env` に `COMFY_MODELS_DIR=/path/to/ComfyUI/models` を書いて再起動します（Docker では同じ絶対パスでマウントされます）。
  **ボタンを押したときだけ**ダウンロードします。`<名前>.part` に書き、サイズと SHA-256 を確かめてから本来の名前にします。途中で止まっても
  （アプリやコンテナが止まっても）、もう一度押すか、次の起動時に続きから再開します
- 取得元: モデルは Hugging Face の [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)（ComfyUI 公式テンプレートと同じ）、
  LoRA は [Kohei-Yamashita/swap-illustration-lora](https://huggingface.co/Kohei-Yamashita/swap-illustration-lora)（`LORA_HF_REPO` / `LORA_SHA256` で変更可）。
  URL は設定（`model_urls`）で上書きできます。Hugging Face のトークン（任意）は Hugging Face のホストにだけ送ります
- 大きさの目安: Turbo / 通常のモデル 各 7.3 GB、テキストエンコーダ 9.4 GB、VAE 0.7 GB、LoRA 168 MB
- LoRA と Qwen-Image 2.1 は Qwen Research License（非商用）です。詳細は各 Hugging Face リポジトリの LICENSE / NOTICE を参照してください

---

## Comfy Cloud で使う

1. [Comfy Cloud](https://docs.comfy.org/) で API キーを作り、画面の **設定 → 実行先・LoRA** で「Comfy Cloud」を選んでキーを入れる
   （または `.env` の `COMFY_CLOUD_API_KEY`）。キーは `data/settings.json`（git 管理外）に保存され、画面には「設定済み」としか出ません
2. API の利用には Comfy Cloud の有料プランが必要です（Karakuri Media Studio での確認による）

接続のしかたは Karakuri Media Studio と同じです: エンドポイントは `https://cloud.comfy.org` 固定、API は `/api` の下、認証は
`X-API-Key` ヘッダー、ジョブの状態は `/api/jobs/{id}`（`/history` は無い）、結果の `/view` は署名 URL への 302、`/interrupt` は無い
（取り消しは手元で結果を捨てるだけ）。

### Comfy Cloud で LoRA を使うには

Comfy Cloud は手元のファイルを直接アップロードできません。LoRA は Hugging Face / Civitai から取り込みます
（[Comfy Cloud のドキュメント「Import models」](https://docs.comfy.org/cloud/import-models)）。

1. Comfy Cloud の画面左の **Models**（Model Library）→ **Import**
2. LoRA の URL（`https://huggingface.co/Kohei-Yamashita/swap-illustration-lora/resolve/main/anime-swap.safetensors`）を貼り、種類に LoRA（`loras`）を選んで取り込む
3. このアプリの 設定 → 実行先・LoRA で Comfy Cloud を選ぶと、Cloud の LoRA 一覧（`/api/object_info` の LoraLoaderModelOnly）から
   ファイル名を選べます。既定は `anime-swap.safetensors`

制約・分からない点:

- 取り込み（Import）は Creator プラン以上、`.safetensors` のみ（ドキュメントによる）。非公開リポジトリは Comfy Cloud の Settings → Secrets に
  Hugging Face のトークンを入れれば取り込めるとされています
- 取り込みを API で行う方法はドキュメントに見当たりません（画面から手で行う）
- 取り込んだ LoRA がワークフロー上でどのファイル名（サブフォルダの有無）になるかはドキュメントに書かれていません。上の一覧で確認してください
- **未確認**: Comfy Cloud に Qwen-Image 2.1 の int8_convrot 版の重み（ワークフローが指定するファイル名）や、`TextEncodeQwenImage21`・
  `QwenImage21Cache`・`SaveImageAdvanced` ノードがあるか（どれも ComfyUI 本体のノードですが、Cloud の ComfyUI の版によります）。
  ファイル名が違う場合、このアプリには Cloud 用にモデルのファイル名を変える設定はまだありません
- API キーが無いため、Comfy Cloud での実際の生成は試していません（接続処理は単体テストのみ）

---

## 指示文

`backend/app/instructions.py` が、LoRA の学習データを作ったテンプレートと**一字一句同じ**英語の指示文を作ります
（`backend/tests/reference/instructions_ref.py` が学習時のスクリプトの無改変の写しで、テストで突き合わせています）。

- 丸あり（枠で指定）: `Replace the person circled in red (marker 1) in <image1> with the person from <image2>, …`（構文 0 の基本形が既定。
  「詳しい設定」で学習時の言い回し 4 種から選べる）
- 丸なし（位置で指定）: 枠と、自動検出で見つかった「置き換えない人」の中心の左右順から、1 人 `the person`／2 人 `on the left / on the right`／
  3 人 `left / middle / right`／4 人以上 `the leftmost person`・`the N-th person from the left`・`the rightmost person`
- 顔アップ（枠の中で顔が大きい、または枠が画像の大部分）: 服の言及を控えめにした学習時の文面（「詳しい設定」で自動／顔アップ／通常）
- 「A の服装のまま」（学習データには無い、このアプリで足した文）: 全員がこの指定なら、B から受け継ぐものから outfit design を外し、
  `Keep the outfit of … exactly as it is in <image1>, including how much of the body is covered (even if the person is partially or fully unclothed); do not use the clothing from <image2>.`
  を足します。一部の枠だけなら学習時の文はそのままで、`However, for …, keep the outfit …` を足します
- 画像の順は `<image1>` = A（または A_marked）、`<image2>` 以降 = 枠 1, 2, … に割り当てた B

A_marked は `backend/app/markers.py` が Pillow で描きます（学習時の `postprocess.py` と同じ: 楕円 = 枠の 1.15 倍 + 短辺の 1.2%、
線幅 max(4, 短辺の 0.8%)、番号バッジ = 半径 max(18, 短辺の 3.2%)・白縁・白い太字、顔を避ける位置。楕円が隣の人や他人の顔に
かかるときは角丸矩形など）。

## 履歴を残さない（データの扱い）

このアプリは生成の履歴を残しません。

- 生成ジョブはサーバーのメモリ上のキューで処理し、送った画像（A_marked・B）と結果は一時フォルダ（`data/tmp/jobs/<id>/`）にだけ置きます。
  ブラウザが結果を受け取る（メモリ上の blob に取り込む）と、すぐにサーバー側の一時ファイルを消します。受け取られなかった場合も、
  ジョブが終わってから 10 分で消します
- アップロードした A・B（`data/tmp/images/`）は編集中のセッションのための一時ファイルで、最後に使ってから 6 時間で消します
- アプリの起動時に一時フォルダを空にします（旧版が作った `data/jobs`・`data/images`・`swap.db` も消します）
- 画面には今回のセッションの結果だけが出ます。リロードすると消えるので、残したい画像は「保存する」でダウンロードしてください
- 残すのは設定（`data/settings.json`）、セットアップの状況（`data/downloads.json`）、検出モデル（`data/detector/`）だけです

**ComfyUI 側**: このアプリの中には残しませんが、ComfyUI 側（output / input フォルダ、ComfyUI の履歴）には
ComfyUI の通常の動作どおり残ります（Comfy Cloud も同様に Cloud 側の扱いに従います）。

## 人物・顔の自動検出

ローカル CPU（onnxruntime）で動く、イラスト向けの YOLOv8 nano モデルを使います（初回に「人物を自動検出」を押したとき
Hugging Face から `data/detector/` に取得。リビジョン固定・SHA-256 確認。合計約 24 MB）。

| 用途 | モデル | ライセンス |
| --- | --- | --- |
| 人物 | [deepghs/anime_person_detection](https://huggingface.co/deepghs/anime_person_detection) `person_detect_v1.1_n` | MIT |
| 顔 | [deepghs/anime_face_detection](https://huggingface.co/deepghs/anime_face_detection) `face_detect_v1.4_n` | MIT |

顔の枠は、丸が他の人の顔にかからないようにする判定と、顔アップの判定に使います。取得できない（オフラインなど）ときは
「検出なし（手動のみ）」で動きます。

## 中断の自動リトライ

同じ ComfyUI を Karakuri Media Studio と共有していると、Karakuri がジョブを取り消すときに呼ぶ `/interrupt` で、このアプリの
実行中のジョブが止まることがあります。`execution_interrupted` を検知したら、このアプリ自身が取り消したのでなければ、20 秒空けて
5 回まで投げ直します。このアプリの「取り消す」は、ComfyUI の実行中のジョブが自分のものだと確かめてから止めます（待ち中なら待ち行列から消すだけ）。

---

## 設定（.env）

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `2760` | 待ち受け（Docker ではホスト側の公開先） |
| `ACCESS_TOKEN` | なし | `HOST` が 127.0.0.1 以外のとき必須（16 文字以上） |
| `REQUIRE_TOKEN` | なし | `1` で 127.0.0.1 でもトークンを要求（トンネルで公開するとき） |
| `COMFY_URL` | `http://127.0.0.1:8188` | ローカル ComfyUI（`./run.sh`） |
| `DOCKER_COMFY_URL` | `http://host.docker.internal:8188` | ローカル ComfyUI（Docker） |
| `COMFY_MODELS_DIR` | なし | ComfyUI の models フォルダ（セットアップのダウンロード先） |
| `COMFY_CLOUD_API_KEY` | なし | Comfy Cloud の API キー（画面からも設定可） |
| `HF_TOKEN` | なし | Hugging Face のトークン（任意） |
| `LORA_HF_REPO` / `LORA_SHA256` | Kohei-Yamashita/swap-illustration-lora / 0e51ca1e… | LoRA の取得元と検証用ハッシュ |
| `SWAP_DATA_DIR` | `./data` | 設定・検出モデル・一時ファイルの置き場 |

画面の設定（実行先・LoRA のファイル名・API キーなど）は `data/settings.json`（git 管理外）に保存されます。

## 構成

```
backend/
  app/
    main.py          FastAPI（API とビルド済みフロントエンドの配信）
    config.py        設定（.env と data/settings.json）
    auth.py          アクセストークン（LAN 公開時）
    instructions.py  指示文（学習時のテンプレート）
    markers.py       A_marked の描画（Pillow）
    workflow.py      ComfyUI のワークフロー組み立て（LoRA の挿入）
    workflows/       ワークフロー JSON（Karakuri Media Studio の写し）
    comfy.py         ローカル ComfyUI / Comfy Cloud のクライアント
    jobs.py          ジョブキュー（メモリ上・同時 1・中断の自動リトライ・一時ファイルの後始末）
    images.py        アップロード画像（一時）・切り抜き
    detector.py      人物・顔の自動検出（onnxruntime）
    model_setup.py   セットアップ（必要ファイルの確認・再開できるダウンロード）
  tests/             pytest
frontend/            React + Vite + TypeScript（PWA）
Dockerfile           マルチステージ（フロントエンドをビルド → Python の実行イメージ）
docker-compose.yml / compose.sh / run.sh / .env.example
```

## 開発・テスト

```bash
./run.sh --test
# 個別に:
(cd backend && ../.venv/bin/python -m pytest -q)
(cd frontend && npm test && npm run typecheck)
```
