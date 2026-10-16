"""ComfyUI / Comfy Cloud クライアント（HTTP はモック）。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.comfy import (ComfyClient, ComfyError, ComfyExecutionError, classify_history, combo_options, error_message,
                       normalize_cloud_job, output_images)
from app.config import Settings


def make(handler, url="https://cloud.comfy.org", key="KEY"):
    return ComfyClient(url, key, transport=httpx.MockTransport(handler))


async def test_cloud_uses_api_prefix_and_api_key():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("x-api-key")))
        if req.url.path == "/api/upload/image":
            assert b'name="type"' in req.content and b"input" in req.content
            return httpx.Response(200, json={"name": "A.png", "subfolder": "swap_studio"})
        if req.url.path == "/api/prompt":
            body = json.loads(req.content)
            assert body["client_id"] == "cid" and "prompt" in body
            return httpx.Response(200, json={"prompt_id": "p1"})
        if req.url.path == "/api/jobs/p1":
            return httpx.Response(200, json={"status": "completed", "outputs": {"8": {"images": [
                {"filename": "o.png", "subfolder": "", "type": "output"}]}}})
        if req.url.path == "/api/view":
            # Cloud は署名 URL への 302
            return httpx.Response(302, headers={"location": "https://storage.example/o.png?sig=1"})
        if req.url.host == "storage.example":
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    c = make(handler)
    assert c.cloud
    name = await c.upload_image(__file__)
    assert name == "swap_studio/A.png"
    pid = await c.queue_prompt({"1": {}}, "cid")
    entry = await c.history(pid)
    assert classify_history(entry) == "success"
    imgs = output_images(entry)
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        p = await c.download(imgs[0], pathlib.Path(td) / "o.png")
        assert p.read_bytes() == b"PNGDATA"
    assert all(k == "KEY" for (_m, path, k) in seen if path.startswith("/api/"))
    assert ("GET", "/api/jobs/p1", "KEY") in seen
    # Cloud には /interrupt が無いので cancel は何も呼ばない
    n = len(seen)
    await c.cancel("p1")
    assert len(seen) == n


def test_cloud_job_normalization():
    assert classify_history(normalize_cloud_job({"status": "pending"}, "x")) == "pending"
    assert classify_history(normalize_cloud_job({"status": "in_progress"}, "x")) == "pending"
    err = normalize_cloud_job({"status": "failed", "error": "boom"}, "x")
    assert classify_history(err) == "error"
    assert "boom" in error_message(err)
    assert classify_history(normalize_cloud_job({"job": {"status": "cancelled"}}, "x")) == "interrupted"
    with pytest.raises(ComfyError):
        normalize_cloud_job({"status": "completed", "outputs": {}}, "x")


def test_local_history_classification():
    assert classify_history({}) == "pending"
    ok = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": {}}
    assert classify_history(ok) == "success"
    intr = {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {}], ["execution_interrupted", {"node_id": "6"}]]}}
    assert classify_history(intr) == "interrupted"
    err = {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_error", {"node_type": "KSampler", "exception_message": "OOM"}]]}}
    assert classify_history(err) == "error"
    assert error_message(err) == "KSampler: OOM"


async def test_local_cancel_only_own_prompt():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, req.content))
        if req.url.path == "/queue" and req.method == "GET":
            return httpx.Response(200, json={"queue_running": [[0, "other", {}, {}, []]],
                                             "queue_pending": [[1, "mine", {}, {}, []]]})
        return httpx.Response(200, json={})

    c = make(handler, "http://127.0.0.1:8188", "")
    assert not c.cloud
    await c.cancel("mine")          # 待ち中 → /queue から delete
    posts = [(p, json.loads(b)) for m, p, b in calls if m == "POST"]
    assert posts == [("/queue", {"delete": ["mine"]})]
    calls.clear()
    await c.cancel("somebody")      # 自分のでもない → 何もしない（/interrupt を呼ばない）
    assert not any(p == "/interrupt" for _m, p, _b in calls)


async def test_queue_400_is_execution_error():
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "Value not in list: lora_name"}})

    c = make(handler, "http://127.0.0.1:8188", "")
    with pytest.raises(ComfyExecutionError):
        await c.queue_prompt({}, "c")


async def test_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused")

    c = make(handler, "http://127.0.0.1:1", "")
    with pytest.raises(ComfyError) as ei:
        await c.history("x")
    assert ei.value.unreachable


def test_from_settings_cloud_requires_key():
    with pytest.raises(ComfyError):
        ComfyClient.from_settings(Settings(target="cloud"))
    c = ComfyClient.from_settings(Settings(target="cloud", comfy_cloud_api_key="k"))
    assert c.cloud and c.base_url == "https://cloud.comfy.org" and c.headers() == {"X-API-Key": "k"}
    local = ComfyClient.from_settings(Settings(local_comfy_url="http://host.docker.internal:8188/"))
    assert not local.cloud and local.base_url == "http://host.docker.internal:8188"


def test_combo_options_shapes():
    assert combo_options({"L": {"input": {"required": {"f": [["a", "b"], {}]}}}}, "L", "f") == ["a", "b"]
    assert combo_options({"L": {"input": {"required": {"f": ["COMBO", {"options": ["c"]}]}}}}, "L", "f") == ["c"]
    assert combo_options({"L": {"input": {"optional": {"f": [{"options": ["d"]}]}}}}, "L", "f") == ["d"]
