"""アップロード画像（A・B）の一時保存と切り抜き。

ブラウザから受け取った画像は、向き（EXIF）を直して RGB の PNG にそろえ、内容のハッシュを ID にして
data/tmp/images/<id>.png に置く（同じ画像は 1 つにまとまる）。透過 PNG（設定画など）は白で塗る。

履歴は残さない方針なので、これは編集中のセッションのための一時ファイル。最後に使ってから
``IMAGE_TTL`` 秒たったものと、アプリの起動時に残っていたものは消す。
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from .config import tmp_dir

#: 長辺の上限（これより大きい画像は縮める。ComfyUI 側も 1024 相当で処理する）
MAX_SIDE = 4096
MAX_BYTES = 40 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{20}$")
#: 最後に使ってからこの秒数たった画像は消す（編集を続けている間は使うたびに延びる）
IMAGE_TTL = 6 * 3600

Image.MAX_IMAGE_PIXELS = 80_000_000


class ImageError(ValueError):
    pass


def images_dir() -> Path:
    d = tmp_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def image_path(image_id: str) -> Path:
    if not ID_RE.match(image_id or ""):
        raise ImageError("画像 ID が不正です")
    p = images_dir() / f"{image_id}.png"
    if not p.exists():
        raise ImageError("画像が見つかりません（一定時間使わなかったか、アプリが再起動したため消えました。もう一度追加してください）")
    try:
        os.utime(p)  # 使ったので期限を延ばす
    except OSError:
        pass
    return p


def _normalize(im: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return im


def _store(im: Image.Image) -> dict:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    data = buf.getvalue()
    image_id = hashlib.sha256(data).hexdigest()[:20]
    p = images_dir() / f"{image_id}.png"
    if not p.exists():
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    return info(image_id, im.size)


def info(image_id: str, size: tuple[int, int] | None = None) -> dict:
    if size is None:
        with Image.open(image_path(image_id)) as im:
            size = im.size
    return {"id": image_id, "width": size[0], "height": size[1], "url": f"/api/images/{image_id}"}


def save_upload(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ImageError("画像が大きすぎます（40MB まで）")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            norm = _normalize(im)
    except ImageError:
        raise
    except Exception as exc:  # noqa: BLE001 - 壊れた画像・未対応の形式
        raise ImageError(f"画像として読めませんでした: {exc}") from exc
    return _store(norm)


def crop(image_id: str, box: list[float]) -> dict:
    """矩形 [x0, y0, x1, y1]（元画像の px）で切り抜いて新しい画像として保存する。"""
    with Image.open(image_path(image_id)) as im:
        W, H = im.size
        x0, y0, x1, y1 = box
        x0, x1 = sorted((max(0, min(W, x0)), max(0, min(W, x1))))
        y0, y1 = sorted((max(0, min(H, y0)), max(0, min(H, y1))))
        if x1 - x0 < 16 or y1 - y0 < 16:
            raise ImageError("切り抜く範囲が小さすぎます")
        out = im.convert("RGB").crop((round(x0), round(y0), round(x1), round(y1)))
    return _store(out)


def open_rgb(image_id: str) -> Image.Image:
    with Image.open(image_path(image_id)) as im:
        return im.convert("RGB")


def sweep(max_age: float = IMAGE_TTL) -> int:
    """最後に使ってから max_age 秒たった画像を消す。消した数を返す。"""
    now = time.time()
    n = 0
    for p in images_dir().glob("*.png"):
        try:
            if now - p.stat().st_mtime > max_age:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n
