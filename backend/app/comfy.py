"""ComfyUI / Comfy Cloud の HTTP クライアント。

Karakuri Media Studio の backend/app/comfy.py と同じ接続のしかた:

- ローカル ComfyUI: ``/prompt`` ``/history/{id}`` ``/upload/image`` ``/view`` ``/object_info`` ``/interrupt``
- Comfy Cloud（``https://cloud.comfy.org``）: 同じ API が ``/api`` の下にある。認証は ``X-API-Key``
  ヘッダー。``/history`` は無く ``/api/jobs/{id}`` で状態を取る。``/view`` は署名 URL への 302 を返す
  （リダイレクトを追う）。``/interrupt`` は無い。API の利用には有料プランが要る。

ジョブの状態はローカルの ``/history`` の形（``{"status": {...}, "outputs": {...}}``）に揃えて返す。
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import COMFY_CLOUD_URL, ComfyTarget, Settings

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 300.0
DOWNLOAD_TIMEOUT = 600.0

#: ComfyUI へ届く前に潰れたことを表すステータス（リバースプロキシ / トンネルの 5xx）
UNREACHABLE_STATUSES = frozenset({502, 503, 504, 520, 521, 522, 523, 524, 530})


class ComfyError(Exception):
    """ComfyUI との通信の失敗（接続不可・タイムアウト・HTTP エラー・不正な応答）。"""

    def __init__(self, message: str, *, status_code: int | None = None, unreachable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.unreachable = unreachable


class ComfyExecutionError(ComfyError):
    """ジョブが ComfyUI 側でエラー終了した。"""


class ComfyInterrupted(ComfyError):
    """ジョブが中断された（execution_interrupted。同じ ComfyUI を使う別アプリの /interrupt など）。"""


def _body_excerpt(response: httpx.Response) -> str:
    """エラー本文の抜粋（HTML は <title> だけ）。"""
    text = (response.text or "").strip()
    ctype = response.headers.get("content-type", "").lower()
    if not ("html" in ctype or text[:200].lstrip().lower().startswith(("<!doctype html", "<html"))):
        return text[:500]
    m = re.search(r"<title[^>]*>(.*?)</title>", text[:4000], re.I | re.S)
    title = " ".join(m.group(1).split())[:120] if m else ""
    return f"({title})" if title else "(HTML エラーページ)"


def combo_options(info: dict[str, Any], class_type: str, field: str) -> list[str]:
    """/object_info の入力定義から選択肢を取り出す（版ごとの形の違いを吸収）。

      classic:  [["a", "b"], {...}]
      dict:     [{"options": ["a", "b"]}, {...}]
      V3/cloud: ["COMBO", {"options": ["a", "b"]}]
    """
    node = info.get(class_type)
    if not node:
        raise ComfyError(f"ComfyUI にノード {class_type} がありません")
    spec = (node.get("input", {}).get("required", {}) or {}).get(field)
    if spec is None:
        spec = (node.get("input", {}).get("optional", {}) or {}).get(field)
    if not isinstance(spec, list) or not spec:
        raise ComfyError(f"{class_type}.{field} の選択肢がありません")
    options = spec[0]
    config = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if isinstance(options, str):
        options = config.get("options", config.get("values", config.get("choices")))
    elif isinstance(options, dict):
        options = options.get("options", options.get("values", []))
    if not isinstance(options, list):
        raise ComfyError(f"{class_type}.{field} は選択式の入力ではありません")
    return [str(o) for o in options]


# Comfy Cloud のジョブ状態 -> ローカルの history の意味
_CLOUD_ERROR_STATUSES = {"failed", "error"}
_CLOUD_CANCELLED = {"cancelled", "canceled", "interrupted"}


def normalize_cloud_job(payload: Any, prompt_id: str) -> dict[str, Any]:
    """``GET /api/jobs/{id}`` の応答をローカルの history の 1 件の形にする。"""
    if not isinstance(payload, dict):
        raise ComfyError("Comfy Cloud の /api/jobs の応答が不正です")
    job = payload.get("job") if isinstance(payload.get("job"), dict) else payload
    status = str(job.get("status") or "").lower()
    outputs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    if status in _CLOUD_ERROR_STATUSES or status in _CLOUD_CANCELLED:
        message = (job.get("error") or job.get("error_message") or job.get("status_message")
                   or f"Comfy Cloud のジョブが {status} になりました")
        kind = "execution_interrupted" if status in _CLOUD_CANCELLED else "execution_error"
        return {"status": {"status_str": "error", "completed": False,
                           "messages": [[kind, {"exception_message": str(message)}]]}}
    if status in {"completed", "success"}:
        if not outputs:
            raise ComfyError(f"Comfy Cloud のジョブ {prompt_id} は完了しましたが出力がありません")
        return {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}
    return {"status": {"status_str": status or "pending", "completed": False, "messages": []}}


def classify_history(entry: dict[str, Any]) -> str:
    """history の 1 件 -> "pending" / "success" / "interrupted" / "error"。"""
    if not entry:
        return "pending"
    st = entry.get("status") or {}
    msgs = st.get("messages") or []
    kinds = [m[0] for m in msgs if isinstance(m, (list, tuple)) and m]
    if "execution_interrupted" in kinds:
        return "interrupted"
    if st.get("status_str") == "error" or "execution_error" in kinds:
        return "error"
    if st.get("completed") or st.get("status_str") == "success":
        return "success"
    return "pending"


def error_message(entry: dict[str, Any]) -> str:
    """エラー終了したジョブの、人が読める理由。"""
    for m in (entry.get("status") or {}).get("messages") or []:
        if isinstance(m, (list, tuple)) and len(m) > 1 and m[0] == "execution_error" and isinstance(m[1], dict):
            d = m[1]
            node = d.get("node_type") or d.get("node_id") or ""
            msg = str(d.get("exception_message") or "").strip()
            return f"{node}: {msg}" if node else msg or "ComfyUI でエラーが発生しました"
    return "ComfyUI でエラーが発生しました"


def output_images(entry: dict[str, Any]) -> list[dict]:
    """history の outputs から画像の一覧（filename / subfolder / type）。"""
    imgs = []
    for out in (entry.get("outputs") or {}).values():
        if isinstance(out, dict):
            for im in out.get("images") or []:
                if isinstance(im, dict) and im.get("filename"):
                    imgs.append(im)
    return imgs


class ComfyClient:
    """接続先 1 つぶんのクライアント（ジョブごとに作る）。"""

    def __init__(self, base_url: str, api_key: str = "", *, cloud: bool | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not base_url:
            raise ComfyError("ComfyUI の URL が設定されていません")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0].lower()
        self.cloud = host.endswith("comfy.org") if cloud is None else cloud
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings, target: ComfyTarget | None = None) -> "ComfyClient":
        t = target or settings.target
        if t == "cloud" and not settings.api_key("cloud"):
            raise ComfyError("Comfy Cloud の API キーが設定されていません（設定 → 実行先）")
        return cls(settings.comfy_url(t), settings.api_key(t), cloud=(t == "cloud"))

    # ------------------------------------------------------------------ 低レベル
    @property
    def prefix(self) -> str:
        return "/api" if self.cloud else ""

    def headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"X-API-Key": self.api_key}

    def _client(self, timeout: float) -> httpx.AsyncClient:
        kw: dict[str, Any] = {}
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.AsyncClient(base_url=self.base_url, headers=self.headers(), timeout=timeout,
                                 follow_redirects=True, **kw)

    async def _request(self, method: str, path: str, *, timeout: float = DEFAULT_TIMEOUT, **kw: Any) -> httpx.Response:
        try:
            async with self._client(timeout) as c:
                r = await c.request(method, path, **kw)
                r.raise_for_status()
                return r
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            hint = ""
            if status in (401, 403) and self.cloud:
                hint = "（Comfy Cloud の API キーと、API が使えるプランかを確認してください）"
            raise ComfyError(f"ComfyUI {method} {path} が失敗しました: HTTP {status} {_body_excerpt(exc.response)}{hint}".rstrip(),
                             status_code=status, unreachable=status in UNREACHABLE_STATUSES) from exc
        except httpx.HTTPError as exc:
            where = "Comfy Cloud" if self.cloud else f"ComfyUI（{self.base_url}）"
            raise ComfyError(f"{where} に接続できません: {type(exc).__name__} {exc}".rstrip(), unreachable=True) from exc

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        try:
            return r.json()
        except ValueError as exc:
            raise ComfyError(f"ComfyUI の応答が JSON ではありません: {exc}") from exc

    # ------------------------------------------------------------------ 情報
    async def object_info(self, class_type: str | None = None) -> dict[str, Any]:
        path = self.prefix + (f"/object_info/{class_type}" if class_type else "/object_info")
        data = self._json(await self._request("GET", path))
        if not isinstance(data, dict):
            raise ComfyError("/object_info の応答が不正です")
        return data

    async def combo(self, class_type: str, field: str) -> list[str]:
        return combo_options(await self.object_info(class_type), class_type, field)

    async def lora_files(self) -> list[str]:
        return await self.combo("LoraLoaderModelOnly", "lora_name")

    async def system_stats(self) -> dict[str, Any]:
        return self._json(await self._request("GET", self.prefix + "/system_stats", timeout=5.0))

    # ------------------------------------------------------------------ 投入・結果
    async def upload_image(self, path: str | Path, subfolder: str = "swap_studio") -> str:
        """``/upload/image`` に送り、ワークフローに書く名前（``subfolder/name``）を返す。"""
        src = Path(path)
        ctype = mimetypes.guess_type(src.name)[0] or "image/png"
        data = {"type": "input", "overwrite": "true"}
        if subfolder:
            data["subfolder"] = subfolder
        payload = self._json(await self._request(
            "POST", self.prefix + "/upload/image", data=data,
            files={"image": (src.name, src.read_bytes(), ctype)}, timeout=UPLOAD_TIMEOUT))
        name = payload.get("name") if isinstance(payload, dict) else None
        if not name:
            raise ComfyError(f"/upload/image の応答が不正です: {payload!r}")
        sub = payload.get("subfolder") or ""
        return f"{sub}/{name}" if sub else str(name)

    async def queue_prompt(self, graph: dict, client_id: str) -> str:
        try:
            r = await self._request("POST", self.prefix + "/prompt", json={"prompt": graph, "client_id": client_id})
        except ComfyError as exc:
            if exc.status_code == 400:
                raise ComfyExecutionError(f"ワークフローが受け付けられませんでした（モデルや LoRA のファイル名を確認してください）: {exc}") from exc
            raise
        payload = self._json(r)
        pid = payload.get("prompt_id") if isinstance(payload, dict) else None
        if not pid:
            raise ComfyError(f"ComfyUI がワークフローを受け付けませんでした: {payload!r}")
        return str(pid)

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """ジョブの状態（ローカルの history の 1 件の形。待ち中は {}）。"""
        if self.cloud:
            return normalize_cloud_job(self._json(await self._request("GET", f"/api/jobs/{prompt_id}")), prompt_id)
        payload = self._json(await self._request("GET", f"/history/{prompt_id}"))
        if not isinstance(payload, dict):
            raise ComfyError("/history の応答が不正です")
        entry = payload.get(prompt_id, {})
        return entry if isinstance(entry, dict) else {}

    async def queue_state(self) -> dict[str, list[str]]:
        """待ち行列の prompt_id（ローカルのみ。Cloud は空）。"""
        if self.cloud:
            return {"running": [], "pending": []}
        q = self._json(await self._request("GET", "/queue", timeout=5.0))

        def ids(items):
            return [str(it[1]) for it in items or [] if isinstance(it, (list, tuple)) and len(it) > 1]
        return {"running": ids(q.get("queue_running")), "pending": ids(q.get("queue_pending"))}

    async def cancel(self, prompt_id: str) -> None:
        """自分のジョブだけを止める（他のアプリのジョブは止めない）。

        待ち中なら待ち行列から消す。実行中なら、その実行中のジョブが自分のものだと確かめて
        から /interrupt を呼ぶ。Comfy Cloud には /interrupt が無いので何もしない（結果を捨てるだけ）。
        """
        if self.cloud:
            return
        state = await self.queue_state()
        if prompt_id in state["pending"]:
            await self._request("POST", "/queue", json={"delete": [prompt_id]}, timeout=5.0)
        elif prompt_id in state["running"]:
            # 新しい ComfyUI は prompt_id 指定の中断に対応（古い版は無視して実行中を止める。
            # 直前に実行中が自分のジョブだと確かめているので、他のジョブを止めることはない）
            await self._request("POST", "/interrupt", json={"prompt_id": prompt_id}, timeout=5.0)

    async def delete_history(self, prompt_id: str) -> None:
        """ComfyUI の履歴（/history）から自分のジョブの記録を消す（ローカルのみ）。

        出力画像のファイルそのものは消えない（ComfyUI にファイルを消す API は無い）。
        """
        if self.cloud:
            return
        await self._request("POST", "/history", json={"delete": [prompt_id]}, timeout=5.0)

    async def download(self, image: dict, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        params = {"filename": image["filename"], "subfolder": image.get("subfolder") or "", "type": image.get("type") or "output"}
        try:
            async with self._client(DOWNLOAD_TIMEOUT) as c:
                async with c.stream("GET", self.prefix + "/view", params=params) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with tmp.open("wb") as fh:
                        async for chunk in r.aiter_bytes():
                            fh.write(chunk)
                    tmp.replace(dest)
        except httpx.HTTPStatusError as exc:
            raise ComfyError(f"結果画像の取得に失敗しました: HTTP {exc.response.status_code}",
                             status_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise ComfyError(f"結果画像の取得に失敗しました: {exc}", unreachable=True) from exc
        return dest

    # ------------------------------------------------------------------ 進捗（WebSocket、任意）
    def ws_url(self, client_id: str) -> str:
        scheme = "wss" if self.base_url.startswith("https://") else "ws"
        host = self.base_url.split("://", 1)[-1]
        return f"{scheme}://{host}/ws?clientId={client_id}"

    async def watch_progress(self, client_id: str, on_progress: Callable[[str | None, float], None]) -> None:
        """WebSocket の progress を受けて on_progress(prompt_id, 0〜1) を呼ぶ。失敗しても黙って終わる。

        進捗は表示のためだけに使う（完了・失敗の判定は history のポーリングで行う）。
        """
        try:
            import websockets
        except ImportError:  # pragma: no cover
            return
        try:
            async with websockets.connect(self.ws_url(client_id), additional_headers=self.headers(),
                                          open_timeout=10, max_size=None) as ws:
                async for raw in ws:
                    if not isinstance(raw, str):
                        continue  # プレビュー画像（バイナリ）は使わない
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if msg.get("type") == "progress":
                        d = msg.get("data") or {}
                        mx = float(d.get("max") or 0)
                        if mx > 0:
                            on_progress(d.get("prompt_id"), min(1.0, float(d.get("value") or 0) / mx))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 進捗は無くても生成はできる
            log.debug("progress websocket closed: %s", exc)


def cloud_url() -> str:
    return COMFY_CLOUD_URL
