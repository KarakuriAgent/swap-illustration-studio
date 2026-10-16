"""セットアップ: 必要ファイルの列挙・有無の判定・ダウンロードの途中再開・LoRA のハッシュ確認。

実際のモデルはダウンロードしない。ローカルの小さなダミーファイルを HTTP（Range 対応）で配って確かめる。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import model_setup as ms
from app.config import DEFAULT_LORA_SHA256, Settings, SettingsUpdate, update_settings

PAYLOAD = os.urandom(3 * 1024 * 1024 + 123)


class Handler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.requests.append({"path": self.path, "range": self.headers.get("Range"),
                                 "auth": self.headers.get("Authorization")})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file.bin")
            self.end_headers()
            return
        if self.path not in ("/file.bin", "/lora.safetensors"):
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            if start >= len(PAYLOAD):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        else:
            self.send_response(200)
        body = PAYLOAD[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    Handler.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_required_files_from_workflows():
    items = ms.required_files(Settings())
    keys = {i["key"] for i in items}
    assert keys == {
        "diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors",
        "diffusion_models/qwen_image_2.1_int8_convrot.safetensors",
        "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
        "vae/qwen_image_2.1_vae_bf16.safetensors",
        "loras/qwen-image-21/anime-swap.safetensors",
    }
    shared = next(i for i in items if i["folder"] == "vae")
    assert shared["used_by"] == ["turbo", "base"]


def test_default_sources():
    s = Settings()
    lora = next(i for i in ms.required_files(s) if i["folder"] == "loras")
    src = ms.source_for(lora, s)
    assert src["url"] == "https://huggingface.co/Kohei-Yamashita/swap-illustration-lora/resolve/main/anime-swap.safetensors"
    assert src["sha256"] == DEFAULT_LORA_SHA256
    s2 = Settings(lora_hf_repo="me/other", lora_sha256="ab" * 32)
    src2 = ms.source_for(lora, s2)
    assert src2["url"].startswith("https://huggingface.co/me/other/resolve/main/")
    assert src2["sha256"] == "ab" * 32 and src2["size"] is None
    vae = next(i for i in ms.required_files(s) if i["folder"] == "vae")
    assert ms.source_for(vae, s)["url"] == ("https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/"
                                            "vae/qwen_image_2.1_vae_bf16.safetensors")


async def test_check_by_object_info_and_by_files(tmp_path, monkeypatch):
    models = tmp_path / "models"
    (models / "vae").mkdir(parents=True)
    (models / "vae" / "qwen_image_2.1_vae_bf16.safetensors").write_bytes(b"x" * 10)   # サイズ違い
    monkeypatch.setenv("COMFY_MODELS_DIR", str(models))
    combos = {"UNETLoader.unet_name": ["qwen_image_2.1_turbo_int8_convrot.safetensors"],
              "CLIPLoader.clip_name": [], "VAELoader.vae_name": [],
              "LoraLoaderModelOnly.lora_name": ["qwen-image-21/anime-swap.safetensors"]}
    res = await ms.check(combos, Settings())
    by = {i["key"]: i for i in res["items"]}
    assert by["diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors"]["ok"]
    assert by["loras/qwen-image-21/anime-swap.safetensors"]["ok"]
    assert not by["diffusion_models/qwen_image_2.1_int8_convrot.safetensors"]["ok"]
    assert by["vae/qwen_image_2.1_vae_bf16.safetensors"]["file"] == "size_mismatch"
    assert not res["all_ok"]
    # ファイルがあれば ComfyUI に聞けなくても OK
    (models / "text_encoders").mkdir()
    big = models / "text_encoders" / "qwen3vl_8b_int8_convrot.safetensors"
    with big.open("wb") as f:
        f.truncate(9350798360)   # 疎なファイル（実際には書かない）
    res2 = await ms.check(None, Settings())
    assert {i["key"]: i["ok"] for i in res2["items"]}["text_encoders/qwen3vl_8b_int8_convrot.safetensors"]


async def test_resume_download(tmp_path, server):
    dest = tmp_path / "m" / "file.bin"
    dest.parent.mkdir()
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(PAYLOAD[:1_000_000])    # 途中まで落ちていた
    st: dict = {}
    sha = hashlib.sha256(PAYLOAD).hexdigest()
    await ms.fetch_resumable(f"{server}/redirect", dest, st, expected_size=len(PAYLOAD), expected_sha256=sha,
                             settings=Settings())
    assert dest.read_bytes() == PAYLOAD
    assert not part.exists()
    ranged = [r for r in Handler.requests if r["path"] == "/file.bin"]
    assert ranged[-1]["range"] == "bytes=1000000-"
    # Hugging Face 以外のホストにトークンは送らない
    assert all(r["auth"] is None for r in Handler.requests)


async def test_size_mismatch_is_detected(tmp_path, server):
    """サーバーは全部送ったのに想定サイズと違う → 続きから取っても直らないので .part も消す。"""
    dest = tmp_path / "file.bin"
    with pytest.raises(ms.SetupError):
        await ms.fetch_resumable(f"{server}/file.bin", dest, {}, expected_size=len(PAYLOAD) + 5, settings=Settings())
    assert not dest.exists()
    assert not dest.with_name("file.bin.part").exists()


async def test_hash_mismatch_discards(tmp_path, server):
    dest = tmp_path / "file.bin"
    with pytest.raises(ms.SetupError):
        await ms.fetch_resumable(f"{server}/file.bin", dest, {}, expected_sha256="0" * 64, settings=Settings())
    assert not dest.exists() and not dest.with_name("file.bin.part").exists()


def test_hf_token_only_for_hf_hosts(monkeypatch):
    s = Settings(hf_token="hf_x")
    assert ms.auth_headers("https://huggingface.co/a/b/resolve/main/c", s) == {"Authorization": "Bearer hf_x"}
    assert ms.auth_headers("https://cdn-lfs.hf.co/x", s) == {"Authorization": "Bearer hf_x"}
    assert ms.auth_headers("https://cas-bridge.xethub.hf.co/x", s) == {"Authorization": "Bearer hf_x"}
    assert ms.auth_headers("https://evil.example/huggingface.co", s) == {}


async def _wait(key):
    for _ in range(200):
        st = ms._state.get(key, {})
        if st.get("status") not in ("downloading", "verifying"):
            return st
        await asyncio.sleep(0.02)
    raise AssertionError("timeout")


async def test_lora_download_with_hash_and_skip_when_present(tmp_path, monkeypatch, server):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("COMFY_MODELS_DIR", str(models))
    sha = hashlib.sha256(PAYLOAD).hexdigest()
    update_settings(SettingsUpdate(lora_sha256=sha,
                                   model_urls={"anime-swap.safetensors": f"{server}/lora.safetensors"}))
    key = "loras/qwen-image-21/anime-swap.safetensors"
    st = ms.start_download(key)
    assert st["status"] == "downloading"
    st = await _wait(key)
    assert st["status"] == "done", st
    dest = models / "loras" / "qwen-image-21" / "anime-swap.safetensors"
    assert dest.read_bytes() == PAYLOAD
    # 既にあるものはダウンロードしない
    n = len(Handler.requests)
    st2 = ms.start_download(key)
    assert st2["status"] == "done" and "すでに" in st2["message"]
    assert len(Handler.requests) == n


async def test_lora_hash_mismatch_is_error(tmp_path, monkeypatch, server):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("COMFY_MODELS_DIR", str(models))
    update_settings(SettingsUpdate(model_urls={"anime-swap.safetensors": f"{server}/lora.safetensors"}))
    key = "loras/qwen-image-21/anime-swap.safetensors"
    ms.start_download(key)   # 既定の SHA-256（本物の LoRA）とは一致しない
    st = await _wait(key)
    assert st["status"] == "error" and "SHA-256" in st["error"]
    assert not (models / "loras" / "qwen-image-21" / "anime-swap.safetensors").exists()


def test_download_requires_models_dir():
    with pytest.raises(ms.SetupError):
        ms.start_download("vae/qwen_image_2.1_vae_bf16.safetensors")


def test_cloud_target_does_not_download(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFY_MODELS_DIR", str(tmp_path))
    with pytest.raises(ms.SetupError):
        ms.start_download("vae/qwen_image_2.1_vae_bf16.safetensors", Settings(target="cloud"))


def test_target_path_stays_inside(tmp_path):
    with pytest.raises(ms.SetupError):
        ms.target_path({"folder": "loras", "filename": "../../etc/passwd"}, tmp_path)


async def test_resume_interrupted_on_startup(tmp_path, monkeypatch, server):
    """前回ダウンロード中のまま止まったもの（.part が残っている）を起動時に続きから再開する。"""
    models = tmp_path / "models"
    (models / "vae").mkdir(parents=True)
    monkeypatch.setenv("COMFY_MODELS_DIR", str(models))
    url = f"{server}/file.bin"
    update_settings(SettingsUpdate(model_urls={"qwen_image_2.1_vae_bf16.safetensors": url}))
    key = "vae/qwen_image_2.1_vae_bf16.safetensors"
    (models / "vae" / "qwen_image_2.1_vae_bf16.safetensors.part").write_bytes(PAYLOAD[:500_000])
    ms._state[key] = {"key": key, "status": "downloading", "received": 500_000, "url": url}
    ms._save_state()
    ms._state.clear()
    assert ms.resume_interrupted() == [key]
    st = await _wait(key)
    assert st["status"] == "done", st
    assert (models / "vae" / "qwen_image_2.1_vae_bf16.safetensors").read_bytes() == PAYLOAD
    assert any(r["range"] == "bytes=500000-" for r in Handler.requests)
