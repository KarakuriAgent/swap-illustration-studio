"""ローカル ComfyUI のセットアップ（必要なモデルと LoRA の確認・ダウンロード・コピー）。

- 必要なファイルは、同梱のワークフロー JSON（Turbo / 通常）のローダーノードから機械的に列挙する
  （UNETLoader → diffusion_models、CLIPLoader → text_encoders、VAELoader → vae）。LoRA は設定の
  ファイル名（既定 qwen-image-21/anime-swap.safetensors → loras）。
- あるかどうかは、ComfyUI の /object_info の選択肢に出ているか、または ``COMFY_MODELS_DIR`` の
  正しいサブフォルダにファイルがあるかで判定する。
- 足りないものは**ユーザーが押したときだけ**ダウンロードする（勝手に始めない）。``<名前>.part`` に
  書き、途中で止まったら Range で続きから取る。サイズ（と分かっていれば SHA-256）を確かめてから
  本来の名前に rename する。進行中の状態は data/downloads.json に残し、アプリ（コンテナ）が
  止まっても次の起動で続きから再開する（ユーザーが一度始めたものに限る）。
- LoRA（anime-swap）は Hugging Face のリポジトリ（設定 / .env の LORA_HF_REPO）から同じしくみで
  ダウンロードし、設定の SHA-256（LORA_SHA256）で確かめる。
- すでに models フォルダにある（または ComfyUI に見えている）ファイルはダウンロードしない。
- Comfy Cloud ではファイルシステムに届かないので使わない。

ダウンロード元の既定値は ComfyUI 公式のワークフローテンプレート（Comfy-Org/Qwen-Image-2.1）と
同じ Hugging Face の URL。Turbo 版はテンプレートに無いが同じリポジトリの diffusion_models/ にある
（サイズ・SHA-256 は Hugging Face の X-Linked-Size / X-Linked-ETag で確認した値）。
リダイレクトは自分で追い、Hugging Face のトークンは Hugging Face のホストにだけ送る
（Karakuri Media Studio の model_download.py と同じ考え方）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import DEFAULT_LORA_LOCAL, DEFAULT_LORA_SHA256, Settings, comfy_models_dir, data_dir, load_settings
from .workflow import LOADER_FOLDERS, required_models

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=120.0, pool=30.0)
CHUNK = 4 * 1024 * 1024
PART_SUFFIX = ".part"
MAX_REDIRECTS = 10
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HF_HOSTS = ("huggingface.co", "hf.co")

HF_BASE = "https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main"


@dataclass(frozen=True)
class Source:
    url: str
    size: int | None = None
    sha256: str | None = None


#: ファイル名 -> 既定のダウンロード元（設定の model_urls で上書きできる）
DEFAULT_SOURCES: dict[str, Source] = {
    "qwen_image_2.1_turbo_int8_convrot.safetensors": Source(
        f"{HF_BASE}/diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors", 7256787829,
        "8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c"),
    "qwen_image_2.1_int8_convrot.safetensors": Source(
        f"{HF_BASE}/diffusion_models/qwen_image_2.1_int8_convrot.safetensors", 7256783064,
        "cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d"),
    "qwen3vl_8b_int8_convrot.safetensors": Source(
        f"{HF_BASE}/text_encoders/qwen3vl_8b_int8_convrot.safetensors", 9350798360,
        "8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f"),
    "qwen_image_2.1_vae_bf16.safetensors": Source(
        f"{HF_BASE}/vae/qwen_image_2.1_vae_bf16.safetensors", 675509688,
        "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9"),
}

#: 既定の LoRA（DEFAULT_LORA_SHA256 のファイル）のサイズ
LORA_FILENAME = "anime-swap.safetensors"
LORA_SIZE = 167830056


class SetupError(Exception):
    pass


class SetupBusy(SetupError):
    pass


# --------------------------------------------------------------------------- 必要なファイル
def required_files(settings: Settings | None = None) -> list[dict]:
    """必要なファイルの一覧（重複なし）。``key`` は ``<フォルダ>/<ファイル名>``。"""
    settings = settings or load_settings()
    items: dict[str, dict] = {}
    for kind in ("turbo", "base"):
        for m in required_models(kind):
            key = f"{m['folder']}/{m['filename']}"
            it = items.setdefault(key, {**m, "key": key, "used_by": []})
            it["used_by"].append(kind)
    lora = settings.lora_name_local or DEFAULT_LORA_LOCAL
    ct = "LoraLoaderModelOnly"
    field, folder = LOADER_FOLDERS[ct]
    items[f"{folder}/{lora}"] = {"class_type": ct, "field": field, "folder": folder, "filename": lora,
                                 "key": f"{folder}/{lora}", "used_by": ["turbo", "base"]}
    return list(items.values())


def source_for(item: dict, settings: Settings | None = None) -> dict:
    """そのファイルの取得元: {"kind": "url"|"none", "url", "size", "sha256"}"""
    settings = settings or load_settings()
    name = item["filename"]
    base = Path(name).name
    override = settings.model_urls.get(name) or settings.model_urls.get(base)
    if item["folder"] == "loras":
        if base != LORA_FILENAME and not override:
            return {"kind": "none", "url": None, "size": None, "sha256": None}
        sha = settings.effective_lora_sha256() if base == LORA_FILENAME else None
        return {"kind": "url", "url": override or settings.lora_url(), "sha256": sha,
                "size": LORA_SIZE if sha == DEFAULT_LORA_SHA256 and not override else None}
    src = DEFAULT_SOURCES.get(base)
    if override:
        same = src is not None and override == src.url
        return {"kind": "url", "url": override, "size": src.size if same else None, "sha256": src.sha256 if same else None}
    if src:
        return {"kind": "url", "url": src.url, "size": src.size, "sha256": src.sha256}
    return {"kind": "none", "url": None, "size": None, "sha256": None}


# --------------------------------------------------------------------------- models フォルダ
def models_dir_status() -> dict:
    root = comfy_models_dir()
    if root is None:
        return {"configured": False, "exists": False, "writable": False, "path": None}
    exists = root.is_dir()
    return {"configured": True, "exists": exists, "writable": exists and os.access(root, os.W_OK), "path": str(root)}


def target_path(item: dict, root: Path | None = None) -> Path:
    """保存先（models フォルダの外に出る指定は拒否）。"""
    base_dir = root or comfy_models_dir()
    if base_dir is None:
        raise SetupError("COMFY_MODELS_DIR（ComfyUI の models フォルダ）が設定されていません")
    base = base_dir.expanduser().resolve()
    rel = Path(item["folder"]) / item["filename"]
    if rel.is_absolute() or ".." in rel.parts:
        raise SetupError(f"不正なファイル名です: {item['filename']}")
    dest = (base / rel).resolve()
    if base not in dest.parents:
        raise SetupError(f"models フォルダの外は指定できません: {item['filename']}")
    return dest


def file_state(item: dict, expected_size: int | None, root: Path | None = None) -> str:
    """models フォルダ上の状態: present / size_mismatch / partial / absent / unknown（フォルダ未設定）"""
    try:
        dest = target_path(item, root)
    except SetupError:
        return "unknown"
    if dest.is_file():
        if expected_size is not None and dest.stat().st_size != expected_size:
            return "size_mismatch"
        return "present"
    if dest.with_name(dest.name + PART_SUFFIX).is_file():
        return "partial"
    return "absent"


async def check(comfy_combos: dict[str, list[str]] | None, settings: Settings | None = None) -> dict:
    """セットアップの状態。comfy_combos = {"UNETLoader.unet_name": [...], ...}（取れなければ None）。"""
    settings = settings or load_settings()
    mdir = models_dir_status()
    out = []
    for it in required_files(settings):
        src = source_for(it, settings)
        fs = file_state(it, src.get("size")) if mdir["exists"] else "unknown"
        in_comfy = None
        if comfy_combos is not None:
            opts = comfy_combos.get(f"{it['class_type']}.{it['field']}")
            if opts is not None:
                names = {o.replace("\\", "/") for o in opts}
                in_comfy = it["filename"] in names
        ok = fs == "present" or bool(in_comfy)
        dl = _state.get(it["key"])
        out.append({
            "key": it["key"], "folder": it["folder"], "filename": it["filename"], "used_by": it["used_by"],
            "ok": ok, "in_comfy": in_comfy, "file": fs,
            "source": src,
            "download": dl,
        })
    return {"models_dir": mdir, "comfy_checked": comfy_combos is not None, "items": out,
            "all_ok": all(i["ok"] for i in out)}


# --------------------------------------------------------------------------- ダウンロード
_state: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}
_state_lock = threading.Lock()


def _state_file() -> Path:
    return data_dir() / "downloads.json"


def _save_state() -> None:
    with _state_lock:
        tmp = _state_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_state_file())


def load_state() -> dict[str, dict]:
    p = _state_file()
    if p.exists():
        try:
            _state.update(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return _state


def downloads() -> list[dict]:
    return list(_state.values())


def auth_headers(url: str, settings: Settings | None = None) -> dict[str, str]:
    """Hugging Face のホストにだけトークンを付ける（リダイレクト先ごとに計算し直す）。"""
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in HF_HOSTS):
        token = (settings or load_settings()).effective_hf_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def check_url(url: str) -> str:
    if urlparse(url or "").scheme not in {"http", "https"}:
        raise SetupError(f"http(s) の URL を指定してください: {url}")
    return url


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def fetch_resumable(url: str, dest: Path, state: dict, *, expected_size: int | None = None,
                          expected_sha256: str | None = None, settings: Settings | None = None,
                          transport: httpx.AsyncBaseTransport | None = None,
                          on_progress=None) -> Path:
    """url を dest に落とす。``dest.part`` があれば続きから（Range）。完了後にサイズ・ハッシュを確認。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + PART_SUFFIX)
    have = part.stat().st_size if part.exists() else 0
    if expected_size is not None and have > expected_size:
        part.unlink()
        have = 0
    state["received"] = have
    kw: dict[str, Any] = {"timeout": TIMEOUT, "follow_redirects": False}
    if transport is not None:
        kw["transport"] = transport
    done = expected_size is not None and have == expected_size
    if not done:
        async with httpx.AsyncClient(**kw) as client:
            address = check_url(url)
            for _ in range(MAX_REDIRECTS + 1):
                headers = auth_headers(address, settings)
                if have:
                    headers["Range"] = f"bytes={have}-"
                async with client.stream("GET", address, headers=headers) as r:
                    if r.status_code in REDIRECT_STATUSES:
                        loc = r.headers.get("location")
                        if not loc:
                            raise SetupError(f"リダイレクト先がありません（HTTP {r.status_code}）")
                        address = check_url(urljoin(address, loc))
                        continue
                    if r.status_code == 416 and have:
                        # 既に全部ある（サーバーが範囲外と答えた）
                        break
                    r.raise_for_status()
                    if r.status_code == 206:
                        mode = "ab"
                        cr = r.headers.get("content-range", "")
                        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr and cr.rsplit("/", 1)[-1].isdigit() else None
                    else:
                        # Range を無視された → 最初から
                        mode, have = "wb", 0
                        cl = r.headers.get("content-length")
                        total = int(cl) if cl and cl.isdigit() else None
                    state["total"] = total or expected_size
                    state["received"] = have
                    last = time.monotonic()
                    with part.open(mode) as f:
                        async for chunk in r.aiter_bytes(CHUNK):
                            f.write(chunk)
                            state["received"] += len(chunk)
                            if time.monotonic() - last > 1.0:
                                last = time.monotonic()
                                if on_progress:
                                    on_progress()
                    break
            else:
                raise SetupError(f"リダイレクトが {MAX_REDIRECTS} 回を超えました")
    size = part.stat().st_size
    want = expected_size or state.get("total")
    if want is not None and size != want:
        server_total = state.get("total")
        if size > want or (server_total is not None and server_total != want and size == server_total):
            # サーバーとしては全部送り終えているのに想定と違う → 続きから取っても直らない
            part.unlink(missing_ok=True)
            raise SetupError(f"ダウンロードしたファイルのサイズが想定と違います（{size} / {want} バイト）。"
                             "ダウンロード元の URL を確認してください")
        raise SetupError(f"サイズが一致しません（{size} / {want} バイト）。もう一度押すと続きから取得します")
    if expected_sha256:
        state["status"] = "verifying"
        if on_progress:
            on_progress()
        digest = await asyncio.to_thread(_sha256_file, part)
        if digest != expected_sha256:
            part.unlink(missing_ok=True)
            raise SetupError("SHA-256 が一致しません（ファイルが壊れています）。もう一度ダウンロードしてください")
    part.replace(dest)
    return dest


async def _run_download(key: str, item: dict, src: dict) -> None:
    st = _state[key]
    try:
        dest = target_path(item)
        await fetch_resumable(src["url"], dest, st, expected_size=src.get("size"), expected_sha256=src.get("sha256"),
                              on_progress=_save_state)
        st.update(status="done", error=None, received=dest.stat().st_size, finished_at=time.time())
    except asyncio.CancelledError:
        st.update(status="paused", error="アプリが停止したため中断しました（続きから再開できます）")
        _save_state()
        raise
    except Exception as exc:  # noqa: BLE001 - 失敗は画面に出すだけ
        msg = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else str(exc) or type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
            msg += "（Hugging Face のトークンが必要な場合は設定で入れてください）"
        st.update(status="error", error=msg)
        log.warning("download failed %s: %s", key, msg)
    _save_state()


def _require_writable() -> None:
    s = models_dir_status()
    if not s["configured"]:
        raise SetupError(".env の COMFY_MODELS_DIR に ComfyUI の models フォルダを書いて再起動してください"
                         "（Docker では同じ絶対パスでマウントされます）")
    if not s["exists"]:
        raise SetupError(f"models フォルダが見つかりません: {s['path']}")
    if not s["writable"]:
        raise SetupError(f"models フォルダに書き込めません: {s['path']}")


def start_download(key: str, settings: Settings | None = None) -> dict:
    """ユーザーが押したときに呼ぶ。LoRA（同梱）はコピー、それ以外は URL からダウンロード。"""
    settings = settings or load_settings()
    if settings.target == "cloud":
        raise SetupError("Comfy Cloud を実行先にしているときはセットアップは使いません")
    _require_writable()
    item = next((i for i in required_files(settings) if i["key"] == key), None)
    if item is None:
        raise SetupError(f"不明なファイルです: {key}")
    if key in _tasks and not _tasks[key].done():
        raise SetupBusy("すでに処理中です")
    src = source_for(item, settings)
    if file_state(item, src.get("size")) == "present":
        st = {"key": key, "status": "done", "received": target_path(item).stat().st_size, "total": src.get("size"),
              "error": None, "url": src.get("url"), "message": "すでにあります（ダウンロードしません）"}
        _state[key] = st
        _save_state()
        return st
    if src["kind"] != "url" or not src.get("url"):
        raise SetupError("ダウンロード元が分かりません。設定でダウンロード元の URL を入れてください")
    check_url(src["url"])
    st = {"key": key, "status": "downloading", "received": 0, "total": src.get("size"), "error": None,
          "url": src["url"], "started_at": time.time()}
    _state[key] = st
    _save_state()
    _tasks[key] = asyncio.create_task(_run_download(key, item, src))
    return st


def resume_interrupted() -> list[str]:
    """起動時: 前回ダウンロード中のまま止まったもの（ユーザーが始めたもの）を続きから再開する。"""
    load_state()
    resumed = []
    for key, st in list(_state.items()):
        if st.get("status") in ("downloading", "verifying", "paused"):
            try:
                start_download(key)
                resumed.append(key)
            except SetupError as exc:
                st.update(status="error", error=f"再開できませんでした: {exc}")
    if resumed:
        log.info("resumed downloads: %s", resumed)
    _save_state()
    return resumed


async def comfy_combos(client) -> dict[str, list[str]] | None:
    """ComfyUI の /object_info からローダーの選択肢を集める（つながらなければ None）。"""
    from .comfy import ComfyError, combo_options

    out: dict[str, list[str]] = {}
    for ct, (field, _folder) in LOADER_FOLDERS.items():
        try:
            info = await client.object_info(ct)
        except ComfyError as exc:
            if exc.unreachable:
                return None   # ComfyUI につながらない
            continue
        try:
            out[f"{ct}.{field}"] = combo_options(info, ct, field)
        except ComfyError:
            pass
    return out
