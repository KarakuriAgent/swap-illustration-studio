"""Swap Illustration Studio の API サーバー（FastAPI）。ビルド済みのフロントエンドも配信する。"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from . import auth, detector, images, model_setup
from .comfy import ComfyClient, ComfyError
from .config import (ROOT, SettingsUpdate, check_auth_config, load_settings, settings_view, token_required,
                     update_settings)
from .jobs import compose, manager, render_marked, startup_cleanup
from .models import CropRequest, DetectRequest, GenerateRequest, LoginRequest, SceneSpec

log = logging.getLogger("swap")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

APP_NAME = "Swap Illustration Studio"
VERSION = "0.1.0"


def frontend_dist() -> Path:
    raw = os.environ.get("SWAP_FRONTEND_DIST", "").strip()
    return Path(raw) if raw else ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_auth_config()
    # 履歴は残さない: 前回の一時ファイル（アップロード画像・送った画像・結果）を消してから始める
    startup_cleanup()
    manager.start()
    model_setup.resume_interrupted()
    yield
    await manager.stop()


app = FastAPI(title=APP_NAME, version=VERSION, lifespan=lifespan)
app.middleware("http")(auth.middleware)


def _bad(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


# --------------------------------------------------------------------------- 認証
@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {"required": token_required(), "ok": auth.token_ok(request)}


@app.post("/api/auth/login")
async def auth_login(body: LoginRequest, request: Request):
    if not token_required():
        return {"ok": True}
    if not auth.check_login(body.token):
        await asyncio.sleep(1.0)  # 総当たりを遅くする
        raise HTTPException(status_code=401, detail="トークンが違います")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, body.token.strip(), max_age=365 * 24 * 3600, httponly=True,
                    samesite="lax", secure=auth.is_https(request), path="/")
    return resp


@app.post("/api/auth/logout")
async def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# --------------------------------------------------------------------------- 設定・状態
@app.get("/api/health")
async def health():
    settings = load_settings()
    out = {"app": APP_NAME, "version": VERSION, "target": settings.target, "comfy_url": settings.comfy_url(),
           "comfy_ok": False, "comfy_error": None}
    try:
        client = ComfyClient.from_settings(settings)
        if client.cloud:
            await client.object_info("LoraLoaderModelOnly")
        else:
            await client.system_stats()
        out["comfy_ok"] = True
    except ComfyError as exc:
        out["comfy_error"] = str(exc)
    return out


@app.get("/api/settings")
async def get_settings():
    return settings_view(load_settings())


@app.put("/api/settings")
async def put_settings(body: SettingsUpdate):
    return settings_view(update_settings(body))


@app.get("/api/loras")
async def list_loras(target: str | None = None):
    settings = load_settings()
    try:
        client = ComfyClient.from_settings(settings, target if target in ("local", "cloud") else None)  # type: ignore[arg-type]
        files = await client.lora_files()
    except ComfyError as exc:
        return {"files": [], "error": str(exc)}
    return {"files": files, "error": None}


# --------------------------------------------------------------------------- 画像
@app.post("/api/images")
async def upload_image(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return await asyncio.to_thread(images.save_upload, data)
    except images.ImageError as exc:
        raise _bad(exc) from exc


@app.get("/api/images/{image_id}")
async def get_image(image_id: str):
    try:
        p = images.image_path(image_id)
    except images.ImageError as exc:
        raise _bad(exc, 404) from exc
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/images/{image_id}/info")
async def image_info(image_id: str):
    try:
        return images.info(image_id)
    except images.ImageError as exc:
        raise _bad(exc, 404) from exc


@app.post("/api/images/{image_id}/crop")
async def crop_image(image_id: str, body: CropRequest):
    try:
        return await asyncio.to_thread(images.crop, image_id, body.box)
    except images.ImageError as exc:
        raise _bad(exc) from exc


@app.post("/api/detect")
async def detect(body: DetectRequest):
    try:
        im = images.open_rgb(body.image_id)
    except images.ImageError as exc:
        raise _bad(exc, 404) from exc
    return await asyncio.to_thread(detector.detect, im)


@app.get("/api/detect/info")
async def detect_info():
    return {"models": detector.licenses()}


# --------------------------------------------------------------------------- 指示文・A_marked のプレビュー
@app.post("/api/instruction")
async def instruction(body: SceneSpec):
    try:
        im = images.open_rgb(body.scene_id)
        return compose(body, im.size)
    except (images.ImageError, ValueError) as exc:
        raise _bad(exc) from exc


@app.post("/api/preview-marked")
async def preview_marked(body: SceneSpec):
    try:
        im, _shapes = await asyncio.to_thread(render_marked, body)
    except (images.ImageError, ValueError) as exc:
        raise _bad(exc) from exc
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- ジョブ
@app.post("/api/jobs")
async def create_job(body: GenerateRequest):
    try:
        return await asyncio.to_thread(manager.submit, body)
    except (images.ImageError, ValueError, ValidationError) as exc:
        raise _bad(exc) from exc


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "ジョブが見つかりません（受け取り済みか、期限切れで消えました）")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    try:
        await manager.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(404, "ジョブが見つかりません") from exc
    return manager.get(job_id)


@app.delete("/api/jobs/{job_id}")
async def discard_job(job_id: str):
    """ブラウザが結果を受け取ったら呼ぶ。サーバー側の一時ファイル（送った画像・結果）を消す。"""
    try:
        ok = await asyncio.to_thread(manager.discard, job_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": ok}


@app.get("/api/jobs/{job_id}/files/{name}")
async def job_file(job_id: str, name: str):
    p = manager.file_path(job_id, name)
    if p is None:
        raise HTTPException(404, "ファイルが見つかりません（受け取り済みか、期限切れで消えました）")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- セットアップ（ローカル ComfyUI）
@app.get("/api/setup")
async def setup_status():
    settings = load_settings()
    combos = None
    comfy_error = None
    try:
        client = ComfyClient.from_settings(settings, "local")
        combos = await model_setup.comfy_combos(client)
        if combos is None:
            comfy_error = f"ローカルの ComfyUI（{client.base_url}）に接続できません"
    except ComfyError as exc:
        comfy_error = str(exc)
    out = await model_setup.check(combos, settings)
    out["comfy_error"] = comfy_error
    out["target"] = settings.target
    return out


@app.post("/api/setup/download/{key:path}")
async def setup_download(key: str):
    try:
        return model_setup.start_download(key)
    except model_setup.SetupBusy as exc:
        raise _bad(exc, 409) from exc
    except model_setup.SetupError as exc:
        raise _bad(exc) from exc


@app.get("/api/setup/downloads")
async def setup_downloads():
    return {"downloads": model_setup.downloads()}


# --------------------------------------------------------------------------- フロントエンド
def _static_file(path: str) -> Path | None:
    dist = frontend_dist().resolve()
    p = (dist / path).resolve()
    if dist in p.parents and p.is_file():
        return p
    return None


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "見つかりません")
    p = _static_file(full_path) if full_path else None
    if p is not None:
        # ハッシュ付きのビルド成果物は長くキャッシュ。SW とマニフェストは毎回確認
        if full_path.startswith("static/"):
            cache = "public, max-age=31536000, immutable"
        else:
            cache = "no-cache"
        return FileResponse(p, headers={"Cache-Control": cache})
    index = _static_file("index.html")
    if index is None:
        return JSONResponse({"detail": "フロントエンドがビルドされていません（npm --prefix frontend run build）"}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
