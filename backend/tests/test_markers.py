"""マーカー（丸）の描画が学習時と同じパラメータになること。"""

from __future__ import annotations

import math

from PIL import Image

from app.markers import MARK_COLORS, Person, assign_faces, draw_marks, ellipse_params, marker_params


def test_marker_params_match_training():
    # 線幅 max(4, 短辺 0.8%)、バッジ半径 max(18, 短辺 3.2%)、余白 短辺 1.2%、数字 1.3 倍
    p = marker_params(1088, 1440)
    assert p["line_width"] == max(4, int(1088 * 0.008)) == 8
    assert p["badge_radius"] == max(18, int(1088 * 0.032)) == 34
    assert math.isclose(p["pad"], 1088 * 0.012)
    assert p["font_size"] == int(34 * 1.3)
    small = marker_params(400, 300)
    assert small["line_width"] == 4 and small["badge_radius"] == 18


def test_colors_match_training():
    assert MARK_COLORS == {1: ("red", (230, 30, 30)), 2: ("blue", (30, 90, 230)),
                           3: ("green", (20, 170, 60)), 4: ("orange", (245, 140, 0))}


def test_ellipse_is_115x_bbox_plus_pad():
    cx, cy, ax, ay = ellipse_params([100, 200, 300, 600], 1000, 1000)
    assert (cx, cy) == (200, 400)
    assert math.isclose(ax, 100 * 1.15 + 12)
    assert math.isclose(ay, 200 * 1.15 + 12)


def _close(c1, c2, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def test_single_person_draws_ellipse_and_badge():
    im = Image.new("RGB", (1000, 1000), (255, 255, 255))
    persons = [Person([300, 200, 700, 900], mark=1)]
    out, shapes = draw_marks(im, persons)
    assert shapes[0]["shape"] == "ellipse"
    cx, cy, ax, ay = ellipse_params([300, 200, 700, 900], 1000, 1000)
    # 楕円の右端の線は赤
    assert _close(out.getpixel((int(cx + ax - 2), int(cy))), MARK_COLORS[1][1])
    # バッジ（左上 225°）は赤の塗りで、中心付近に白い数字
    bx, by = shapes[0]["badge"]
    assert math.isclose(bx, cx + ax * math.cos(math.radians(225)), abs_tol=1)
    r = marker_params(1000, 1000)["badge_radius"]
    assert _close(out.getpixel((bx - r // 2, by + r // 2)), MARK_COLORS[1][1])
    # 元画像は変えない
    assert im.getpixel((int(cx + ax - 2), int(cy))) == (255, 255, 255)


def test_ellipse_over_neighbor_becomes_rounded_rect():
    im = Image.new("RGB", (1000, 800), (255, 255, 255))
    persons = [Person([100, 100, 480, 780], mark=1), Person([330, 100, 710, 780], mark=2)]
    _, shapes = draw_marks(im, persons)
    assert [s["shape"] for s in shapes] == ["rounded_rect", "rounded_rect"]
    assert shapes[0]["neighbor_overlap"] > 0.04


def test_badge_avoids_faces():
    im = Image.new("RGB", (1000, 1000), (255, 255, 255))
    p = Person([300, 200, 700, 900], mark=1)
    cx, cy, ax, ay = ellipse_params(p.box, 1000, 1000)
    tl = (cx + ax * math.cos(math.radians(225)), cy + ay * math.sin(math.radians(225)))
    # 左上の候補位置に顔を置く → 右上（315°）に逃げる
    p.face = [tl[0] - 60, tl[1] - 60, tl[0] + 60, tl[1] + 60]
    _, shapes = draw_marks(im, [p])
    bx, _by = shapes[0]["badge"]
    assert bx > cx


def test_assign_faces_to_smallest_containing_box():
    big = Person([0, 0, 1000, 1000], key="big")
    small = Person([600, 100, 900, 900], mark=1, key="small")
    assign_faces([big, small], [[650, 150, 800, 300], [100, 100, 200, 200], [5000, 5000, 5100, 5100]])
    assert small.face == [650, 150, 800, 300]
    assert big.face == [100, 100, 200, 200]
