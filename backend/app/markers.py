"""A に番号付きの丸（マーカー）を描いて A_marked を作る（Pillow）。

学習データ（qwen-swap-lora/scripts/postprocess.py の draw_marks）と同じ見た目にする:

- 楕円 = 人物の枠の中心・同じ縦横比で、半径を枠の 1.15 倍 + 短辺の 1.2% の余白
  （学習時は差分画素から 1.0〜1.45 倍を決めていたが、推論時は差分が無いので基準値の 1.15 倍）
- 線幅 = max(4, 短辺の 0.8%)、色は 1=赤 (230,30,30) / 2=青 (30,90,230) / 3=緑 (20,170,60) / 4=橙 (245,140,0)
- 楕円が隣の人物の中心部に大きくかかる、または輪郭線が他の人物の顔にかかるときは
  角丸矩形 → 余白なし矩形 → 横を縮めた矩形の順に、顔にかからないものを選ぶ
- 番号バッジ = 半径 max(18, 短辺の 3.2%) の同色の円・白縁・白い太字の番号。どの人物の顔とも
  重ならない位置を、楕円なら左上 → 右上 → … の順に探す
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

MARK_COLORS = {
    1: ("red", (230, 30, 30)),
    2: ("blue", (30, 90, 230)),
    3: ("green", (20, 170, 60)),
    4: ("orange", (245, 140, 0)),
}

#: 学習データと同じ DejaVu Sans Bold（Docker イメージには fonts-dejavu-core を入れる）
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]

#: 楕円の倍率（学習時の基準値）
ELLIPSE_SCALE = 1.15


def _font(size: int):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


@dataclass
class Person:
    """A の中の人物 1 人（置き換え対象 or そのまま残す人）。"""

    box: list[float]                      # [x0, y0, x1, y1]（A の px）
    face: list[float] | None = None       # 顔の枠（分かれば）
    mark: int | None = None               # 置き換え対象なら枠番号 1〜4
    key: str = field(default="")


def marker_params(width: int, height: int) -> dict:
    """線幅・バッジ半径・余白（学習時と同じ式）。"""
    short = min(width, height)
    return {
        "line_width": max(4, int(short * 0.008)),
        "badge_radius": max(18, int(short * 0.032)),
        "pad": 0.012 * short,
        "font_size": int(max(18, int(short * 0.032)) * 1.3),
    }


def ellipse_params(bb: Sequence[float], width: int, height: int) -> tuple[float, float, float, float]:
    """楕円の (中心 x, 中心 y, 横半径, 縦半径)。"""
    x0, y0, x1, y1 = bb
    pad = 0.012 * min(width, height)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = max((x1 - x0) / 2, 1), max((y1 - y0) / 2, 1)
    return cx, cy, hx * ELLIPSE_SCALE + pad, hy * ELLIPSE_SCALE + pad


def _overlap_frac_ellipse(cx, cy, ax, ay, box) -> float:
    """box（他人物の中心部）のうち楕円内に入る割合（格子サンプリング）。"""
    x0, y0, x1, y1 = box
    n, inside = 0, 0
    for i in range(12):
        for j in range(12):
            x = x0 + (x1 - x0) * (i + 0.5) / 12
            y = y0 + (y1 - y0) * (j + 0.5) / 12
            n += 1
            if ((x - cx) / ax) ** 2 + ((y - cy) / ay) ** 2 <= 1:
                inside += 1
    return inside / n


def _core(box, f=0.25):
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * f, (y1 - y0) * f
    return [x0 + dx, y0 + dy, x1 - dx, y1 - dy]


def _dist_circle_rect(px, py, r, rect) -> float:
    x0, y0, x1, y1 = rect
    dx = max(x0 - px, 0, px - x1)
    dy = max(y0 - py, 0, py - y1)
    return math.hypot(dx, dy) - r


def assign_faces(persons: list[Person], faces: list[Sequence[float]]) -> None:
    """検出した顔の枠を、その中心を含む人物（含む中で一番小さい枠）に割り当てる。

    すでに face を持っている人物には割り当てない。1 つの顔は 1 人にだけ。
    """
    for f in sorted(faces, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        fx, fy = (f[0] + f[2]) / 2, (f[1] + f[3]) / 2
        cands = [p for p in persons if p.face is None and p.box[0] <= fx <= p.box[2] and p.box[1] <= fy <= p.box[3]]
        if not cands:
            continue
        best = min(cands, key=lambda p: (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]))
        best.face = list(f)


def draw_marks(image: Image.Image, persons: list[Person]) -> tuple[Image.Image, list[dict]]:
    """置き換え対象（mark あり）に丸を描いた画像と、選んだ形の記録を返す。"""
    im = image.convert("RGB").copy()
    W, H = im.size
    draw = ImageDraw.Draw(im)
    prm = marker_params(W, H)
    lw, r = prm["line_width"], prm["badge_radius"]
    font = _font(prm["font_size"])
    faces = [p.face for p in persons if p.face]
    shapes = []
    for idx, p in enumerate(sorted([p for p in persons if p.mark], key=lambda p: p.mark)):
        _, color = MARK_COLORS[p.mark]
        bb = p.box
        others = [o for o in persons if o is not p]
        cx, cy, ax, ay = ellipse_params(bb, W, H)
        worst = 0.0
        for o in others:
            worst = max(worst, _overlap_frac_ellipse(cx, cy, ax, ay, _core(o.box)))
        pad = prm["pad"]
        # 他の人物の顔（5% 拡張）に輪郭線がかからない形を選ぶ
        other_faces = []
        for o in others:
            if o.face:
                f0 = o.face
                ex, ey = (f0[2] - f0[0]) * 0.05, (f0[3] - f0[1]) * 0.05
                other_faces.append([f0[0] - ex, f0[1] - ey, f0[2] + ex, f0[3] + ey])

        def outline_pts(kind, box=None):
            if kind == "ellipse":
                return [(cx + ax * math.cos(math.radians(t)), cy + ay * math.sin(math.radians(t))) for t in range(0, 360, 3)]
            x0, y0, x1, y1 = box
            n = 60
            return ([(x0 + (x1 - x0) * i / n, y0) for i in range(n + 1)] + [(x0 + (x1 - x0) * i / n, y1) for i in range(n + 1)]
                    + [(x0, y0 + (y1 - y0) * i / n) for i in range(n + 1)] + [(x1, y0 + (y1 - y0) * i / n) for i in range(n + 1)])

        def hits(pts_):
            return sum(1 for (x, y) in pts_ for f in other_faces if f[0] <= x <= f[2] and f[1] <= y <= f[3])

        sx = (bb[2] - bb[0]) * 0.10
        own = p.face if p.face else [bb[2], 0, bb[0], 0]
        options = [
            ("ellipse", None),
            ("rounded_rect", [bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad]),
            ("rect_tight", [bb[0], bb[1], bb[2], bb[3]]),
            ("rect_shrunk", [min(bb[0] + sx, own[0] - pad), bb[1] - pad, max(bb[2] - sx, own[2] + pad), bb[3] + pad]),
        ]
        if worst > 0.04:      # 隣の人物の中心部に大きくかかる楕円は使わない
            options = options[1:]
        scored = [(hits(outline_pts(k, b)), i, k, b) for i, (k, b) in enumerate(options)]
        face_hits, _, shape, box = min(scored)
        if shape == "ellipse":
            draw.ellipse([cx - ax, cy - ay, cx + ax, cy + ay], outline=color, width=lw)
            angs = [225, 315, 180, 0, 135, 45, 250, 290]   # 画面座標（y 下向き）で 225°=左上
            cands = [(cx + ax * math.cos(math.radians(t)), cy + ay * math.sin(math.radians(t))) for t in angs]
        else:
            rx0, ry0, rx1, ry1 = [min(max(v, lw), lim - lw) for v, lim in zip(box, (W, H, W, H))]
            rad = int(min(W, H) * 0.05) if shape == "rounded_rect" else int(min(W, H) * 0.02)
            draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=rad, outline=color, width=lw)
            cands = [(rx0, ry0), (rx1, ry0), (rx0, (ry0 + ry1) / 2), (rx1, (ry0 + ry1) / 2), (rx0, ry1), (rx1, ry1)]
        # バッジ位置：画面内にクランプ → 顔からの距離が十分なものを優先順に
        best, best_d = None, None
        for (px, py) in cands:
            px = min(max(px, r + 2), W - r - 2)
            py = min(max(py, r + 2), H - r - 2)
            d = min([_dist_circle_rect(px, py, r, f) for f in faces] or [1e9])
            if d > r * 0.3:
                best = (px, py)
                break
            if best_d is None or d > best_d:
                best, best_d = (px, py), d
        px, py = best
        draw.ellipse([px - r, py - r, px + r, py + r], fill=color, outline=(255, 255, 255), width=max(2, lw // 2))
        draw.text((px, py), str(p.mark), fill=(255, 255, 255), font=font, anchor="mm")
        shapes.append({"mark": p.mark, "shape": shape, "neighbor_overlap": round(worst, 3),
                       "outline_face_hits": face_hits, "badge": [round(px), round(py)]})
    return im, shapes
