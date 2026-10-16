"""生成ジョブ（メモリ上のキュー、同時 1 件）。履歴は残さない。

1 ジョブ = 「生成」ボタン 1 回。枚数ぶん（シードを +1 ずつ）ComfyUI に 1 枚ずつ投げる。

- A_marked（または A）と B 群を ComfyUI にアップロード → ワークフローを組んで /prompt → 完了まで
  /history（Comfy Cloud は /api/jobs）をポーリング → 結果を一時フォルダ（data/tmp/jobs/<id>/）に受け取る。
- **履歴を残さない**: ジョブはメモリにだけ持つ。ブラウザが結果を受け取ったら ``DELETE /api/jobs/{id}``
  で一時ファイルごと消す。受け取られなくても、終わってから ``JOB_TTL`` 秒で消す。アプリの起動時には
  一時フォルダを空にする。ComfyUI 側に残る生成画像・アップロードした画像は、``COMFY_OUTPUT_DIR`` /
  ``COMFY_INPUT_DIR`` が設定されていれば消す（ComfyUI に削除 API が無いため）。履歴（/history）の
  記録は API で消す。
- 進捗は ComfyUI の WebSocket の progress を拾う（取れなくても生成はできる）。
- **中断の自動リトライ**: 同じ ComfyUI を Karakuri Media Studio と共有していると、Karakuri がジョブを
  取り消すときに呼ぶ /interrupt でこちらの実行中のジョブが止まることがある。execution_interrupted を
  検知したら、こちらが取り消したのでなければ、間隔を空けて数回まで投げ直す。
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from . import images
from .comfy import (ComfyClient, ComfyError, ComfyExecutionError, ComfyInterrupted, classify_history,
                    error_message, output_images)
from .config import comfy_input_dir, comfy_output_dir, load_settings, tmp_dir
from .instructions import TargetSpec, build_instruction, is_face_closeup
from .markers import Person, assign_faces, draw_marks
from .models import GenerateRequest, SceneSpec
from .workflow import build_edit

log = logging.getLogger(__name__)

#: 中断されたときの投げ直し（回数・間隔）
MAX_RETRIES = 5
RETRY_WAIT = 20.0
#: 状態のポーリング間隔（ローカル / Cloud）
POLL_LOCAL = 1.0
POLL_CLOUD = 3.0
#: ポーリング中の通信エラーを何回まで我慢するか（ComfyUI の再起動などの一時的な切断）
MAX_POLL_FAILURES = 30
#: 1 枚あたりの待ち時間の上限（ほかのジョブの後ろで待つこともあるので長め）
IMAGE_TIMEOUT = 3 * 3600
#: 終わったジョブを（ブラウザが受け取らなくても）消すまでの秒数
JOB_TTL = 10 * 60
#: 期限切れの掃除の間隔
SWEEP_INTERVAL = 60.0

FINISHED = ("done", "error", "cancelled")


class JobCancelled(Exception):
    pass


def jobs_dir() -> Path:
    d = tmp_dir() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _remove_inside(base: Path | None, rel: str) -> bool:
    """base の中の rel を消す（base の外は触らない）。消せたら True。"""
    if base is None or not rel:
        return False
    try:
        root = base.expanduser().resolve()
        p = (root / rel).resolve()
        if root not in p.parents or not p.is_file():
            return False
        p.unlink()
        return True
    except OSError as exc:
        log.info("could not remove %s: %s", rel, exc)
        return False


# --------------------------------------------------------------------------- 指示文と A_marked
def _clamp(box: list[float], W: int, H: int) -> list[float]:
    x0, y0, x1, y1 = box
    return [max(0.0, min(W, x0)), max(0.0, min(H, y0)), max(0.0, min(W, x1)), max(0.0, min(H, y1))]


def scene_persons(spec: SceneSpec, W: int, H: int) -> list[Person]:
    persons = [Person(_clamp(t.box, W, H), mark=i + 1, key=f"t{i}") for i, t in enumerate(spec.targets)]
    persons += [Person(_clamp(o.box, W, H), key=f"o{i}") for i, o in enumerate(spec.others)]
    assign_faces(persons, [_clamp(f, W, H) for f in spec.faces])
    return persons


def compose(spec: SceneSpec, size: tuple[int, int]) -> dict[str, Any]:
    """指示文（と判定の結果・注意書き）を作る。"""
    W, H = size
    persons = scene_persons(spec, W, H)
    targets = [p for p in persons if p.mark]
    others = [p for p in persons if not p.mark]
    for p in targets:
        if p.box[2] - p.box[0] < 8 or p.box[3] - p.box[1] < 8:
            raise ValueError(f"枠 {p.mark} が小さすぎるか、画像の外にあります")
    if spec.face_mode == "auto":
        face = all(is_face_closeup(p.box, W, H, p.face) for p in targets)
    else:
        face = spec.face_mode == "on"
    tspecs = [TargetSpec(p.box, t.outfit) for p, t in zip(targets, spec.targets)]
    prompt = build_instruction(tspecs, spec.mode, face, [o.box for o in others], spec.template, random.Random(0))
    warnings = []
    if spec.mode == "position":
        if not others and not face:
            warnings.append("置き換えない人物の枠がありません。画面に他の人物がいるなら「人物を自動検出」を使うと位置の言葉が正確になります。")
        boxes = [p.box for p in persons]
        cs = sorted((b[0] + b[2]) / 2 for b in boxes)
        if any(b - a < 0.04 * W for a, b in zip(cs, cs[1:])):
            warnings.append("横に並ぶ位置が近い人物がいます。取り違えやすいので「枠で指定」をおすすめします。")
    return {"prompt": prompt, "face": face, "warnings": warnings}


def render_marked(spec: SceneSpec) -> tuple[Image.Image, list[dict]]:
    im = images.open_rgb(spec.scene_id)
    return draw_marks(im, scene_persons(spec, *im.size))


# --------------------------------------------------------------------------- 表示用
def job_out(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if job is None:
        return None
    jid = job["id"]
    base = f"/api/jobs/{jid}/files/"
    out = {k: job.get(k) for k in ("id", "created_at", "finished_at", "status", "message", "error", "progress",
                                   "prompt", "request", "settings")}
    out["inputs"] = {k: base + v for k, v in job["inputs"].items()}
    out["results"] = [{**r, "url": base + r["file"]} for r in job["results"]]
    return out


def friendly_error(exc: Exception, client: ComfyClient | None, lora: str | None) -> str:
    text = str(exc)
    if isinstance(exc, ComfyError) and exc.unreachable:
        if client is not None and client.cloud:
            return "Comfy Cloud に接続できません。ネットワークと API キーを確認してください。"
        url = client.base_url if client else "ComfyUI"
        return f"ローカルの ComfyUI（{url}）に接続できません。ComfyUI が起動しているか、設定の URL を確認してください。"
    if lora and "lora_name" in text:
        return (f"LoRA「{lora}」が ComfyUI に見つかりません。設定 → セットアップで LoRA を用意するか、"
                f"LoRA のファイル名を確認してください。（{text[:300]}）")
    if any(k in text for k in ("unet_name", "clip_name", "vae_name")):
        return f"モデルのファイルが ComfyUI に見つかりません。設定 → セットアップで確認してください。（{text[:300]}）"
    return text[:1000] or type(exc).__name__


# --------------------------------------------------------------------------- キュー
class JobManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.jobs: dict[str, dict[str, Any]] = {}     # メモリにだけ持つ（再起動で消える）
        self.cancel_flags: set[str] = set()
        self.current_pid: dict[str, tuple[ComfyClient, str]] = {}
        self._worker: asyncio.Task | None = None
        self._sweeper: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            # キューはイベントループに結びつくので、起動のたびに作り直す
            self.queue = asyncio.Queue()
            self._worker = asyncio.create_task(self._loop())
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop(self) -> None:
        for t in (self._worker, self._sweeper):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._worker = self._sweeper = None

    # ---------------------------------------------------------------- 投入
    def submit(self, req: GenerateRequest) -> dict[str, Any]:
        settings = load_settings()
        for t in req.targets:
            if t.ref >= len(req.refs):
                raise ValueError("枠に割り当てた人物（B）がありません")
        scene = images.open_rgb(req.scene_id)
        info = compose(req, scene.size)
        prompt = (req.prompt_override or "").strip() or info["prompt"]

        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        d = jobs_dir() / jid
        d.mkdir(parents=True)
        inputs: dict[str, str] = {}
        if req.mode == "marked":
            marked, _shapes = draw_marks(scene, scene_persons(req, *scene.size))
            marked.save(d / "A_marked.png")
            inputs["canvas"] = "A_marked.png"
        else:
            scene.save(d / "A.png")
            inputs["canvas"] = "A.png"
        for i, t in enumerate(req.targets, start=1):
            shutil.copyfile(images.image_path(req.refs[t.ref]), d / f"B{i}.png")
            inputs[f"B{i}"] = f"B{i}.png"

        gs = req.settings
        target = gs.target or settings.target
        resolved = {
            "target": target,
            "model": gs.model,
            "lora_name": gs.lora_name or settings.lora_name(target),
            "strength": round(gs.strength, 3),
            "seed": gs.seed if gs.seed is not None else random.randint(0, 2**31 - 1),
            "count": gs.count,
            "face": info["face"],
            "prompt_edited": bool((req.prompt_override or "").strip()),
        }
        job = {"id": jid, "created_at": time.time(), "finished_at": None, "status": "queued", "message": None,
               "error": None, "progress": 0.0, "prompt": prompt, "request": req.model_dump(),
               "settings": resolved, "inputs": inputs, "results": []}
        self.jobs[jid] = job
        self.queue.put_nowait(jid)
        return job_out(job)  # type: ignore[return-value]

    async def cancel(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] == "queued":
            job.update(status="cancelled", finished_at=time.time(), message="取り消しました")
            return
        if job["status"] == "running":
            self.cancel_flags.add(job_id)
            cur = self.current_pid.get(job_id)
            if cur:
                client, pid = cur
                try:
                    await client.cancel(pid)
                except ComfyError as exc:
                    log.info("cancel failed: %s", exc)

    def get(self, job_id: str) -> dict[str, Any] | None:
        return job_out(self.jobs.get(job_id))

    def file_path(self, job_id: str, name: str) -> Path | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        allowed = set(job["inputs"].values()) | {r["file"] for r in job["results"]}
        if name not in allowed:
            return None
        p = jobs_dir() / job_id / name
        return p if p.is_file() else None

    def discard(self, job_id: str) -> bool:
        """終わったジョブを一時ファイルごと消す（ブラウザが結果を受け取ったあと / 期限切れ）。"""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        if job["status"] not in FINISHED:
            raise RuntimeError("生成中のジョブは消せません（先に取り消してください）")
        self.jobs.pop(job_id, None)
        shutil.rmtree(jobs_dir() / job_id, ignore_errors=True)
        return True

    def sweep(self, now: float | None = None) -> list[str]:
        """終わってから JOB_TTL 秒たったジョブと、どのジョブにも属さない一時フォルダを消す。"""
        now = now or time.time()
        gone = [jid for jid, j in self.jobs.items()
                if j["status"] in FINISHED and j.get("finished_at") and now - j["finished_at"] > JOB_TTL]
        for jid in gone:
            self.discard(jid)
        for d in jobs_dir().iterdir():
            if d.is_dir() and d.name not in self.jobs:
                shutil.rmtree(d, ignore_errors=True)
        images.sweep()
        return gone

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL)
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 - 掃除の失敗で止めない
                log.exception("sweep failed")

    # ---------------------------------------------------------------- 実行
    async def _loop(self) -> None:
        while True:
            jid = await self.queue.get()
            try:
                job = self.jobs.get(jid)
                if job is None or job["status"] != "queued":
                    continue
                await self.run_job(job)
            except Exception:  # noqa: BLE001 - ワーカーは止めない
                log.exception("job %s crashed", jid)
            finally:
                self.queue.task_done()

    async def run_job(self, job: dict[str, Any], client: ComfyClient | None = None) -> None:
        jid = job["id"]
        st = job["settings"]
        d = jobs_dir() / jid
        job.update(status="running", message="準備中", progress=0.0)
        watcher: asyncio.Task | None = None
        uploaded: list[str] = []
        try:
            if client is None:
                client = ComfyClient.from_settings(load_settings(), st["target"])
            client_id = uuid.uuid4().hex
            state = {"pid": None, "index": 0}

            def on_progress(pid: str | None, frac: float) -> None:
                if pid and pid == state["pid"]:
                    job["progress"] = round((state["index"] + frac) / st["count"], 3)

            watcher = asyncio.create_task(client.watch_progress(client_id, on_progress))
            job["message"] = "画像をアップロード中"
            order = ["canvas"] + [f"B{i}" for i in range(1, len(job["inputs"]))]
            for key in order:
                if key in job["inputs"]:
                    up = d / f"swap_{jid}_{key}.png"
                    shutil.copyfile(d / job["inputs"][key], up)
                    try:
                        uploaded.append(await client.upload_image(up))
                    finally:
                        up.unlink(missing_ok=True)
            for i in range(st["count"]):
                state["index"] = i
                seed = int(st["seed"]) + i
                graph = build_edit(job["prompt"], uploaded, seed, st["model"], st["lora_name"], st["strength"])
                t0 = time.time()
                entry, pid = await self._run_one(jid, client, graph, client_id, state, i, st["count"])
                imgs = output_images(entry)
                if not imgs:
                    raise ComfyError("ComfyUI から結果の画像が返ってきませんでした")
                name = f"out_{i + 1}_seed{seed}.png"
                await client.download(imgs[0], d / name)
                await self._cleanup_comfy_output(client, pid, imgs)
                job["results"].append({"file": name, "seed": seed, "elapsed": round(time.time() - t0, 1)})
                job["progress"] = (i + 1) / st["count"]
            job.update(status="done", message=None, progress=1.0)
        except JobCancelled:
            job.update(status="cancelled", message="取り消しました")
        except Exception as exc:  # noqa: BLE001
            log.warning("job %s failed: %s", jid, exc)
            job.update(status="error", message=None, error=friendly_error(exc, client, st.get("lora_name")))
        finally:
            job["finished_at"] = time.time()
            if watcher:
                watcher.cancel()
            if client is not None and not client.cloud:
                for name in uploaded:
                    _remove_inside(comfy_input_dir(), name)
            self.cancel_flags.discard(jid)
            self.current_pid.pop(jid, None)

    async def _cleanup_comfy_output(self, client: ComfyClient, pid: str, imgs: list[dict]) -> None:
        """ComfyUI 側に残った結果を消す（ローカルのみ。ファイルは output フォルダの設定があるときだけ）。"""
        if client.cloud:
            return
        for im in imgs:
            if im.get("type", "output") == "output":
                sub = im.get("subfolder") or ""
                _remove_inside(comfy_output_dir(), f"{sub}/{im['filename']}" if sub else im["filename"])
        try:
            await client.delete_history(pid)
        except ComfyError as exc:
            log.info("could not delete ComfyUI history %s: %s", pid, exc)

    async def _run_one(self, jid: str, client: ComfyClient, graph: dict, client_id: str, state: dict,
                       index: int, count: int) -> tuple[dict, str]:
        """1 枚ぶん。中断されたら（自分で取り消したのでなければ）間隔を空けて投げ直す。"""
        job = self.jobs[jid]
        attempt = 0
        label = f"{index + 1}/{count} 枚目"
        while True:
            if jid in self.cancel_flags:
                raise JobCancelled()
            pid = await client.queue_prompt(graph, client_id)
            state["pid"] = pid
            self.current_pid[jid] = (client, pid)
            job["message"] = f"{label}を生成中" + (f"（投げ直し {attempt}/{MAX_RETRIES}）" if attempt else "")
            try:
                return await self._wait(jid, client, pid, label), pid
            except ComfyInterrupted:
                if jid in self.cancel_flags:
                    raise JobCancelled()
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise ComfyError(f"ComfyUI でジョブが {MAX_RETRIES + 1} 回中断されました（同じ ComfyUI を使う別のアプリが"
                                     "中断している可能性があります）。しばらくしてから再生成してください。")
                msg = (f"{label}が中断されました（同じ ComfyUI を使う別のアプリの取り消しに巻き込まれた可能性）。"
                       f"{int(RETRY_WAIT)} 秒後に投げ直します（{attempt}/{MAX_RETRIES}）")
                log.info("job %s: %s", jid, msg)
                job["message"] = msg
                await self._sleep_unless_cancelled(jid, RETRY_WAIT)

    async def _sleep_unless_cancelled(self, jid: str, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if jid in self.cancel_flags:
                raise JobCancelled()
            await asyncio.sleep(min(0.5, max(0.0, end - time.monotonic())))

    async def _wait(self, jid: str, client: ComfyClient, pid: str, label: str) -> dict:
        job = self.jobs[jid]
        interval = POLL_CLOUD if client.cloud else POLL_LOCAL
        failures = 0
        t0 = time.monotonic()
        while True:
            try:
                entry = await client.history(pid)
                failures = 0
            except ComfyError as exc:
                if not exc.unreachable:
                    raise
                failures += 1
                if failures > MAX_POLL_FAILURES:
                    raise
                entry = {}
            kind = classify_history(entry)
            if kind == "success":
                return entry
            if kind == "interrupted":
                raise ComfyInterrupted("execution_interrupted")
            if kind == "error":
                raise ComfyExecutionError(error_message(entry))
            if jid in self.cancel_flags and client.cloud:
                raise JobCancelled()   # Cloud は止められないので結果を待たずに抜ける
            if not client.cloud:
                try:
                    q = await client.queue_state()
                    if pid in q["pending"]:
                        ahead = q["pending"].index(pid) + len(q["running"])
                        job["message"] = f"{label}: ComfyUI の順番待ち（前に {ahead} 件）"
                    elif pid in q["running"]:
                        job["message"] = f"{label}を生成中"
                except ComfyError:
                    pass
            if time.monotonic() - t0 > IMAGE_TIMEOUT:
                raise ComfyError("時間内に生成が終わりませんでした")
            await asyncio.sleep(interval)


def startup_cleanup() -> None:
    """起動時: 一時フォルダを空にし、旧版が残した履歴（data/jobs・data/images・swap.db）を消す。"""
    from .config import data_dir

    shutil.rmtree(tmp_dir(), ignore_errors=True)
    tmp_dir()
    base = data_dir()
    for name in ("jobs", "images"):
        shutil.rmtree(base / name, ignore_errors=True)
    for name in ("swap.db", "swap.db-wal", "swap.db-shm"):
        (base / name).unlink(missing_ok=True)


manager = JobManager()
