"""ジョブの実行（ComfyUI は偽物）: 中断の自動リトライ、エラー、取り消し、一時ファイルの後始末。"""

from __future__ import annotations

import io
import time

import pytest
from PIL import Image

from app import images, jobs
from app.models import GenerateRequest


def _png(size=(400, 300), color=(200, 220, 240)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeClient:
    """ComfyClient の代わり。history の返り値を順に返す。"""

    cloud = False
    base_url = "http://fake:8188"

    def __init__(self, script):
        self.script = list(script)    # 投入ごとの結果: "interrupted" / "success" / "error"
        self.queued = []
        self.uploaded = []
        self.cancelled = []

    async def upload_image(self, path, subfolder="swap_studio"):
        self.uploaded.append(path.name)
        return f"{subfolder}/{path.name}"

    async def queue_prompt(self, graph, client_id):
        self.queued.append(graph)
        return f"p{len(self.queued)}"

    async def history(self, pid):
        kind = self.script[int(pid[1:]) - 1]
        if kind == "interrupted":
            return {"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}
        if kind == "error":
            return {"status": {"status_str": "error", "messages": [
                ["execution_error", {"node_type": "KSampler", "exception_message": "CUDA OOM"}]]}}
        return {"status": {"status_str": "success", "completed": True},
                "outputs": {"8": {"images": [{"filename": f"{pid}.png", "subfolder": "", "type": "output"}]}}}

    async def queue_state(self):
        return {"running": [], "pending": []}

    async def cancel(self, pid):
        self.cancelled.append(pid)

    async def download(self, image, dest):
        dest.write_bytes(_png((40, 30)))
        return dest

    async def watch_progress(self, client_id, cb):
        return None


@pytest.fixture
def req():
    a = images.save_upload(_png((400, 300)))
    b1 = images.save_upload(_png((100, 200), (255, 0, 0)))
    b2 = images.save_upload(_png((100, 200), (0, 0, 255)))
    return GenerateRequest(scene_id=a["id"], refs=[b1["id"], b2["id"]],
                           targets=[{"box": [10, 20, 150, 290], "ref": 0}, {"box": [220, 20, 380, 290], "ref": 1}],
                           settings={"seed": 11, "count": 2, "strength": 1.0})


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(jobs, "RETRY_WAIT", 0.0)
    monkeypatch.setattr(jobs, "POLL_LOCAL", 0.0)


async def test_submit_writes_inputs_and_prompt(req):
    m = jobs.JobManager()
    job = m.submit(req)
    assert job["status"] == "queued"
    assert job["prompt"].startswith("Replace the person circled in red (marker 1) in <image1>")
    d = jobs.jobs_dir() / job["id"]
    assert {p.name for p in d.iterdir()} == {"A_marked.png", "B1.png", "B2.png"}
    # 一時フォルダ（data/tmp）の中だけに置く
    assert "tmp" in d.parts
    assert job["settings"]["seed"] == 11 and job["settings"]["lora_name"] == "qwen-image-21/anime-swap.safetensors"
    # A_marked には赤い線が入っている
    marked = Image.open(d / "A_marked.png").convert("RGB")
    assert any(px[0] > 200 and px[1] < 60 for px in marked.getdata())


async def test_interrupted_is_retried(req):
    m = jobs.JobManager()
    job = m.submit(req)
    fake = FakeClient(["interrupted", "interrupted", "success", "success"])
    await m.run_job(m.jobs[job["id"]], client=fake)
    done = m.jobs[job["id"]]
    assert done["status"] == "done", done["error"]
    assert [r["seed"] for r in done["results"]] == [11, 12]
    assert len(fake.queued) == 4
    # 投げ直しも同じシード、2 枚目は +1
    assert [g["6"]["inputs"]["seed"] for g in fake.queued] == [11, 11, 11, 12]
    # A_marked, B1, B2 の順にアップロード
    assert [n.split("_", 2)[-1] for n in fake.uploaded] == ["canvas.png", "B1.png", "B2.png"]
    g = fake.queued[0]
    assert g["20"]["inputs"]["lora_name"] == "qwen-image-21/anime-swap.safetensors"
    for r in done["results"]:
        assert (jobs.jobs_dir() / job["id"] / r["file"]).is_file()


async def test_gives_up_after_max_retries(req, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_RETRIES", 2)
    m = jobs.JobManager()
    job = m.submit(req)
    await m.run_job(m.jobs[job["id"]], client=FakeClient(["interrupted"] * 10))
    done = m.jobs[job["id"]]
    assert done["status"] == "error"
    assert "中断" in done["error"]


async def test_execution_error_is_reported(req):
    m = jobs.JobManager()
    job = m.submit(req)
    await m.run_job(m.jobs[job["id"]], client=FakeClient(["error"]))
    done = m.jobs[job["id"]]
    assert done["status"] == "error" and "CUDA OOM" in done["error"]


async def test_own_cancel_is_not_retried(req):
    m = jobs.JobManager()
    job = m.submit(req)
    fake = FakeClient(["interrupted", "success", "success"])
    m.cancel_flags.add(job["id"])   # こちらが取り消した
    await m.run_job(m.jobs[job["id"]], client=fake)
    assert m.jobs[job["id"]]["status"] == "cancelled"


async def test_discard_and_ttl_remove_temp_files(req, monkeypatch):
    m = jobs.JobManager()
    job = m.submit(req)
    with pytest.raises(RuntimeError):
        m.discard(job["id"])            # 生成中・待ち中は消せない
    await m.run_job(m.jobs[job["id"]], client=FakeClient(["success", "success"]))
    d = jobs.jobs_dir() / job["id"]
    assert d.is_dir() and m.file_path(job["id"], m.jobs[job["id"]]["results"][0]["file"])
    assert m.discard(job["id"])          # ブラウザが受け取った
    assert not d.exists() and m.get(job["id"]) is None

    job2 = m.submit(req)
    await m.run_job(m.jobs[job2["id"]], client=FakeClient(["success", "success"]))
    assert m.sweep() == []               # まだ期限内
    assert m.sweep(now=time.time() + jobs.JOB_TTL + 1) == [job2["id"]]
    assert not (jobs.jobs_dir() / job2["id"]).exists()


def test_startup_cleanup_removes_legacy_history(tmp_data):
    (tmp_data / "jobs" / "old").mkdir(parents=True)
    (tmp_data / "images").mkdir()
    (tmp_data / "swap.db").write_bytes(b"")
    (tmp_data / "tmp" / "jobs" / "x").mkdir(parents=True)
    (tmp_data / "settings.json").write_text("{}")
    jobs.startup_cleanup()
    assert not (tmp_data / "jobs").exists() and not (tmp_data / "images").exists()
    assert not (tmp_data / "swap.db").exists()
    assert list((tmp_data / "tmp").iterdir()) == []
    assert (tmp_data / "settings.json").exists()   # 設定は残す


async def test_position_mode_sends_plain_a(req):
    req.mode = "position"
    m = jobs.JobManager()
    job = m.submit(req)
    assert job["inputs"]["canvas"].endswith("/A.png")
    assert "A_marked" not in str(job["inputs"])
    assert job["prompt"].startswith("In <image1>, replace the person on the left with the person from <image2>")


def test_prompt_override(req):
    req.prompt_override = "custom text"
    job = jobs.JobManager().submit(req)
    assert job["prompt"] == "custom text" and job["settings"]["prompt_edited"]


def test_bad_ref_rejected(req):
    req.targets[1].ref = 3
    with pytest.raises(ValueError):
        jobs.JobManager().submit(req)
