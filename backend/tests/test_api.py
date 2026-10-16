"""API（FastAPI の TestClient）。ComfyUI には繋がない。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import detector


def _png(size=(400, 300), mode="RGB", color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://127.0.0.1:9")   # 繋がらない先
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_upload_crop_instruction_preview(client):
    r = client.post("/api/images", files={"file": ("a.png", _png((400, 300)), "image/png")})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["width"] == 400 and a["height"] == 300
    # 透過 PNG は白で塗る
    b = client.post("/api/images", files={"file": ("b.png", _png((100, 200), "RGBA", (0, 0, 0, 0)), "image/png")}).json()
    img = Image.open(io.BytesIO(client.get(b["url"]).content))
    assert img.getpixel((5, 5)) == (255, 255, 255)
    c = client.post(f"/api/images/{b['id']}/crop", json={"box": [10, 20, 90, 180]}).json()
    assert (c["width"], c["height"]) == (80, 160)

    spec = {"scene_id": a["id"], "targets": [{"box": [10, 20, 150, 290], "ref": 0}]}
    r = client.post("/api/instruction", json=spec)
    assert r.status_code == 200
    assert r.json()["prompt"].startswith("Replace the person circled in red (marker 1) in <image1> with the person")
    r = client.post("/api/preview-marked", json=spec)
    assert r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (400, 300)

    bad = client.post("/api/images", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400 and "読め" in bad.json()["detail"]


def test_settings_hide_secrets(client):
    r = client.put("/api/settings", json={"comfy_cloud_api_key": "secret-key", "target": "cloud"})
    body = r.json()
    assert body["comfy_cloud_api_key_set"] is True
    assert "secret-key" not in r.text
    assert client.get("/api/settings").json()["target"] == "cloud"


def test_health_reports_unreachable(client):
    h = client.get("/api/health").json()
    assert h["comfy_ok"] is False and "接続できません" in h["comfy_error"]


def test_detect_without_model_falls_back(client, monkeypatch):
    def unavailable(m):
        raise detector.DetectorUnavailable("offline")

    monkeypatch.setattr(detector, "ensure_model", unavailable)
    detector._sessions.clear()
    a = client.post("/api/images", files={"file": ("a.png", _png(), "image/png")}).json()
    r = client.post("/api/detect", json={"image_id": a["id"]}).json()
    assert r["available"] is False and r["persons"] == [] and "手動" in r["message"]


def test_unknown_job_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs").json() == {"jobs": []}


def test_token_required_on_lan(monkeypatch):
    monkeypatch.setenv("SWAP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("ACCESS_TOKEN", "t" * 24)
    monkeypatch.setenv("COMFY_URL", "http://127.0.0.1:9")
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/settings").status_code == 401
        assert c.get("/api/auth/status").json() == {"required": True, "ok": False}
        assert c.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
        r = c.post("/api/auth/login", json={"token": "t" * 24})
        assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
        assert c.get("/api/settings").status_code == 200       # Cookie で通る
        c.cookies.clear()
        assert c.get("/api/settings", headers={"Authorization": "Bearer " + "t" * 24}).status_code == 200


def test_lan_without_token_refuses_to_start(monkeypatch):
    monkeypatch.setenv("SWAP_BIND_HOST", "0.0.0.0")
    from app.main import app
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_detector_helpers():
    assert detector.infer_size(1088, 1440) == (480, 640)
    boxes = [([0, 0, 10, 10], 0.9), ([1, 1, 10, 10], 0.8), ([50, 50, 60, 60], 0.7)]
    assert [s for _b, s in detector.nms(boxes)] == [0.9, 0.7]
