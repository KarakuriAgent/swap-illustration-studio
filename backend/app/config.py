"""アプリの設定。

設定の出所は 2 つ:

- 環境変数（``.env`` を run.sh / docker compose が読み込む）… 起動時に決まるもの
  （データの置き場、待受、アクセストークン、ComfyUI の models フォルダなど）。
- ``data/settings.json`` … 画面の「設定」から変えるもの（実行先、LoRA ファイル名、
  Comfy Cloud の API キー、Hugging Face トークンなど）。git 管理外の data/ に置く。

秘密情報（Comfy Cloud の API キー・HF トークン）は環境変数でも settings.json でも
渡せる。settings.json 側が空なら環境変数を使う。API の応答には値そのものを出さない。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

#: リポジトリのルート（backend/app/config.py から 2 つ上）
ROOT = Path(__file__).resolve().parents[2]

ComfyTarget = Literal["local", "cloud"]

#: Comfy Cloud のエンドポイント（固定。Karakuri Media Studio と同じ）
COMFY_CLOUD_URL = "https://cloud.comfy.org"

#: LoRA の既定のファイル名。ローカルの ComfyUI ではサブフォルダ付き、
#: Comfy Cloud ではインポート時のファイル名（フォルダ無し）になる想定。
DEFAULT_LORA_LOCAL = "qwen-image-21/anime-swap.safetensors"
DEFAULT_LORA_CLOUD = "anime-swap.safetensors"

#: LoRA を置いている Hugging Face のリポジトリ（.env の LORA_HF_REPO や設定で変えられる）
DEFAULT_LORA_HF_REPO = "Kohei-Yamashita/swap-illustration-lora"
#: 配布している anime-swap.safetensors（round1, step 1500）の SHA-256
DEFAULT_LORA_SHA256 = "0e51ca1e452bce7b8406d1be4808a15cc1feb237c86ed39f70d2e6b1379d63b0"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def data_dir() -> Path:
    """設定・検出モデル・一時ファイルの置き場（既定はリポジトリ直下の data/）。履歴は置かない。"""
    raw = _env("SWAP_DATA_DIR")
    path = Path(raw).expanduser() if raw else ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tmp_dir() -> Path:
    """一時ファイルの置き場（data/tmp）。起動時に中身を消す。履歴は残さない方針なので、
    アップロード画像・送った画像・結果はここにだけ置き、期限が来たら消す。"""
    d = data_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env_path(name: str) -> Path | None:
    raw = _env(name)
    return Path(raw).expanduser() if raw else None


def comfy_output_dir() -> Path | None:
    """ローカル ComfyUI の output フォルダ（``COMFY_OUTPUT_DIR``）。設定されていれば、
    結果を受け取ったあとに ComfyUI 側に残った生成画像を消す（ComfyUI に削除 API が無いため）。"""
    return _env_path("COMFY_OUTPUT_DIR")


def comfy_input_dir() -> Path | None:
    """ローカル ComfyUI の input フォルダ（``COMFY_INPUT_DIR``）。設定されていれば、
    アップロードした A_marked・B をジョブのあとで消す。"""
    return _env_path("COMFY_INPUT_DIR")


def comfy_models_dir() -> Path | None:
    """ローカル ComfyUI の models フォルダ（``COMFY_MODELS_DIR``。未設定なら None）。

    Karakuri Media Studio と同じく環境変数だけを見る。Docker ではホストの models
    フォルダを同じ絶対パスでマウントして初めて書けるので、パスの出所を ``.env``
    （compose のマウント元と同じ変数）に一本化している。
    """
    raw = _env("COMFY_MODELS_DIR")
    return Path(raw).expanduser() if raw else None


def default_local_comfy_url() -> str:
    return _env("COMFY_URL", "http://127.0.0.1:8188") or "http://127.0.0.1:8188"


# --------------------------------------------------------------------------- 待受・認証


def bind_host() -> str:
    """外から見た待受アドレス（run.sh / compose が ``SWAP_BIND_HOST`` に入れる）。

    Docker ではコンテナ内の uvicorn は常に 0.0.0.0 で待つので、実際の待受ではなく
    「ホスト側でどこに公開しているか」でトークンの要否を決める。
    """
    return _env("SWAP_BIND_HOST", "127.0.0.1") or "127.0.0.1"


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def access_token() -> str:
    return _env("ACCESS_TOKEN")


def token_required() -> bool:
    """アクセストークンが必要か（ループバック以外で待ち受けるとき、または明示指定）。"""
    if _env("REQUIRE_TOKEN") in {"1", "true", "yes"}:
        return True
    return bind_host() not in LOOPBACK_HOSTS


def check_auth_config() -> None:
    """LAN に公開するのにトークンが無い構成は起動させない。"""
    if token_required() and len(access_token()) < 16:
        raise RuntimeError(
            "LAN 越しに公開する設定（HOST が 127.0.0.1 以外）では、.env に 16 文字以上の "
            "ACCESS_TOKEN が必要です。例: ACCESS_TOKEN=$(openssl rand -hex 24)"
        )


# --------------------------------------------------------------------------- 画面から変える設定


class Settings(BaseModel):
    """``data/settings.json`` に保存する設定。"""

    target: ComfyTarget = "local"
    local_comfy_url: str = ""
    comfy_cloud_api_key: str = ""
    hf_token: str = ""
    lora_name_local: str = DEFAULT_LORA_LOCAL
    lora_name_cloud: str = DEFAULT_LORA_CLOUD
    #: LoRA の取得元（Hugging Face のリポジトリ "owner/name"。空なら環境変数 LORA_HF_REPO → 既定値）
    lora_hf_repo: str = ""
    #: LoRA の SHA-256（空なら環境変数 LORA_SHA256 → 既定値）。ダウンロード後の検証に使う
    lora_sha256: str = ""
    #: セットアップ用のダウンロード元 URL の上書き（ファイル名 -> URL）
    model_urls: dict[str, str] = Field(default_factory=dict)

    # ---- 実効値（環境変数との合成）
    def comfy_url(self, target: ComfyTarget | None = None) -> str:
        t = target or self.target
        if t == "cloud":
            return COMFY_CLOUD_URL
        return (self.local_comfy_url or default_local_comfy_url()).rstrip("/")

    def api_key(self, target: ComfyTarget | None = None) -> str:
        t = target or self.target
        if t == "cloud":
            return self.comfy_cloud_api_key or _env("COMFY_CLOUD_API_KEY")
        return ""

    def effective_hf_token(self) -> str:
        return self.hf_token or _env("HF_TOKEN")

    def effective_lora_hf_repo(self) -> str:
        return (self.lora_hf_repo or _env("LORA_HF_REPO") or DEFAULT_LORA_HF_REPO).strip("/ ")

    def effective_lora_sha256(self) -> str:
        return (self.lora_sha256 or _env("LORA_SHA256") or DEFAULT_LORA_SHA256).lower()

    def lora_url(self) -> str:
        """LoRA のダウンロード元（既定: https://huggingface.co/<repo>/resolve/main/anime-swap.safetensors）。"""
        return f"https://huggingface.co/{self.effective_lora_hf_repo()}/resolve/main/anime-swap.safetensors"

    def lora_name(self, target: ComfyTarget | None = None) -> str:
        t = target or self.target
        return self.lora_name_cloud if t == "cloud" else self.lora_name_local


class SettingsView(BaseModel):
    """画面に返す設定（秘密情報は「入っているか」だけ）。"""

    target: ComfyTarget
    local_comfy_url: str
    local_comfy_url_default: str
    comfy_cloud_api_key_set: bool
    hf_token_set: bool
    lora_name_local: str
    lora_name_cloud: str
    lora_hf_repo: str
    lora_hf_repo_effective: str
    lora_sha256: str
    lora_sha256_effective: str
    model_urls: dict[str, str]
    comfy_models_dir: str | None
    token_required: bool


class SettingsUpdate(BaseModel):
    """``PUT /api/settings``。None の項目は変えない。秘密情報は空文字で消す。"""

    target: ComfyTarget | None = None
    local_comfy_url: str | None = None
    comfy_cloud_api_key: str | None = None
    hf_token: str | None = None
    lora_name_local: str | None = None
    lora_name_cloud: str | None = None
    lora_hf_repo: str | None = None
    lora_sha256: str | None = None
    model_urls: dict[str, str] | None = None


_lock = threading.Lock()


def _settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        return Settings()
    try:
        return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        # 壊れた設定ファイルで起動できなくなるより、既定値で動く方がよい
        return Settings()


def save_settings(settings: Settings) -> None:
    path = _settings_path()
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # API キーを含むので本人だけ読めるように
        except OSError:
            pass
        tmp.replace(path)


def update_settings(update: SettingsUpdate) -> Settings:
    current = load_settings()
    changes = {k: v for k, v in update.model_dump().items() if v is not None}
    if "local_comfy_url" in changes:
        changes["local_comfy_url"] = changes["local_comfy_url"].strip().rstrip("/")
    for k in ("lora_name_local", "lora_name_cloud", "lora_hf_repo", "comfy_cloud_api_key", "hf_token"):
        if k in changes:
            changes[k] = changes[k].strip()
    if "lora_sha256" in changes:
        changes["lora_sha256"] = changes["lora_sha256"].strip().lower()
    if "model_urls" in changes:
        changes["model_urls"] = {k: v.strip() for k, v in changes["model_urls"].items() if v.strip()}
    new = current.model_copy(update=changes)
    save_settings(new)
    return new


def settings_view(settings: Settings) -> SettingsView:
    models = comfy_models_dir()
    return SettingsView(
        target=settings.target,
        local_comfy_url=settings.local_comfy_url,
        local_comfy_url_default=default_local_comfy_url(),
        comfy_cloud_api_key_set=bool(settings.api_key("cloud")),
        hf_token_set=bool(settings.effective_hf_token()),
        lora_name_local=settings.lora_name_local,
        lora_name_cloud=settings.lora_name_cloud,
        lora_hf_repo=settings.lora_hf_repo,
        lora_hf_repo_effective=settings.effective_lora_hf_repo(),
        lora_sha256=settings.lora_sha256,
        lora_sha256_effective=settings.effective_lora_sha256(),
        model_urls=settings.model_urls,
        comfy_models_dir=str(models) if models else None,
        token_required=token_required(),
    )
