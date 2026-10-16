"""A の人物（イラスト）と顔の自動検出（ローカル CPU、onnxruntime）。

使うモデル（どちらも MIT ライセンス、YOLOv8 nano を ONNX にしたもの、各 約 12MB）:

- 人物: deepghs/anime_person_detection の ``person_detect_v1.1_n``（しきい値 0.327）
- 顔:   deepghs/anime_face_detection の ``face_detect_v1.4_n``（しきい値 0.278）

重みは初めて「人物を自動検出」を押したときに Hugging Face から data/detector/ に取ってくる
（リビジョン固定・SHA-256 を確認）。取れない（オフライン等）・onnxruntime が無いときは
「検出なし（手動のみ）」として動く。

前処理・後処理は deepghs の imgutils（detect/yolo）と同じ考え方: 長辺を 640 に縮め、縦横を 32 の
倍数にそろえて（余白は足さない）0〜1 の RGB を入れる。出力 (1, 4+クラス数, N) の
(cx, cy, w, h, score) から、しきい値と NMS（IoU 0.7）で枠を選ぶ。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image

from .config import data_dir

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetModel:
    key: str
    repo: str
    revision: str
    path: str
    sha256: str
    size: int
    threshold: float

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.path}"


MODELS = {
    "person": DetModel("person", "deepghs/anime_person_detection", "e39c744c22432ad01f91dd254fe2b02c8d878b8c",
                       "person_detect_v1.1_n/model.onnx",
                       "6fcdfc6af18b3a26aca62aad0e00faffbeea23413abf868808d2d98d399999c9", 12102560, 0.327),
    "face": DetModel("face", "deepghs/anime_face_detection", "784dc4c0bb692351ddcdbe6131a050b17d3025d5",
                     "face_detect_v1.4_n/model.onnx",
                     "fd860b650a4377046842c3cd80d01b0b408bdfbdb4acee5759630f82c6ef04a9", 12102558, 0.278),
}

MAX_INFER_SIZE = 640
ALIGN = 32
IOU_THRESHOLD = 0.7

_lock = threading.Lock()
_sessions: dict[str, object] = {}


class DetectorUnavailable(RuntimeError):
    pass


def model_dir() -> Path:
    d = data_dir() / "detector"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(m: DetModel) -> Path:
    """重みを用意する（無ければダウンロードしてハッシュを確認）。"""
    dest = model_dir() / f"{m.key}_{Path(m.path).parent.name}.onnx"
    if dest.exists() and dest.stat().st_size == m.size:
        return dest
    part = dest.with_suffix(".part")
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as c:
            with c.stream("GET", m.url) as r:
                r.raise_for_status()
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise DetectorUnavailable(f"検出モデルをダウンロードできませんでした（{m.repo}）: {exc}") from exc
    if _sha256(part) != m.sha256:
        part.unlink(missing_ok=True)
        raise DetectorUnavailable(f"検出モデルのハッシュが一致しません（{m.repo}）")
    part.replace(dest)
    return dest


def _session(key: str):
    with _lock:
        if key in _sessions:
            return _sessions[key]
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise DetectorUnavailable("onnxruntime が入っていないため自動検出は使えません") from exc
        path = ensure_model(MODELS[key])
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        sess = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        _sessions[key] = sess
        return sess


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(boxes: list[tuple[list[float], float]], iou: float = IOU_THRESHOLD) -> list[tuple[list[float], float]]:
    keep: list[tuple[list[float], float]] = []
    for b, s in sorted(boxes, key=lambda t: -t[1]):
        if all(_iou(b, k[0]) <= iou for k in keep):
            keep.append((b, s))
    return keep


def infer_size(w: int, h: int) -> tuple[int, int]:
    r = MAX_INFER_SIZE / max(w, h)
    nw = max(ALIGN, int(round(w * r / ALIGN)) * ALIGN)
    nh = max(ALIGN, int(round(h * r / ALIGN)) * ALIGN)
    return nw, nh


def _run(key: str, im: Image.Image) -> list[dict]:
    import numpy as np

    sess = _session(key)
    m = MODELS[key]
    W, H = im.size
    nw, nh = infer_size(W, H)
    x = np.asarray(im.convert("RGB").resize((nw, nh), Image.BILINEAR), dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0].T  # (N, 4+nc)
    scores = out[:, 4:].max(axis=1)
    cand = []
    for row, s in zip(out[scores > m.threshold], scores[scores > m.threshold]):
        cx, cy, w, h = (float(v) for v in row[:4])
        sx, sy = W / nw, H / nh
        box = [max(0.0, (cx - w / 2) * sx), max(0.0, (cy - h / 2) * sy), min(W, (cx + w / 2) * sx), min(H, (cy + h / 2) * sy)]
        cand.append((box, float(s)))
    return [{"box": [round(v, 1) for v in b], "score": round(s, 3)} for b, s in nms(cand)]


def detect(im: Image.Image) -> dict:
    """{"available", "persons": [{"box", "score"}], "faces": [...], "message"}"""
    try:
        persons = _run("person", im)
        faces = _run("face", im)
    except DetectorUnavailable as exc:
        log.warning("detector unavailable: %s", exc)
        return {"available": False, "persons": [], "faces": [], "message": f"{exc}（手動で枠を描いてください）"}
    persons.sort(key=lambda p: (p["box"][0] + p["box"][2]) / 2)
    return {"available": True, "persons": persons, "faces": faces,
            "message": "" if persons else "人物が見つかりませんでした。枠を手で描いてください。"}


def licenses() -> list[dict]:
    return [{"key": m.key, "repo": m.repo, "file": m.path, "license": "MIT", "url": f"https://huggingface.co/{m.repo}"}
            for m in MODELS.values()]
