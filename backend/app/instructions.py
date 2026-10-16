"""LoRA「anime-swap」に渡す英語の指示文を組み立てる。

学習時のテンプレート（qwen-swap-lora/scripts/instructions.py の英語版）と**一字一句同じ文面**を
作る。テンプレート関数は学習用の写しで、``keep=False``（既定）のときの出力は元の関数と同一
（tests/test_instructions.py で元のファイルの写しと突き合わせている）。

- <image1> = 編集キャンバス A（丸あり A_marked または丸なし A）、<image2> 以降 = 参照人物 B1, B2, …
- MARKED[k](n, face)   丸あり。丸 i（1=赤, 2=青, 3=緑, 4=橙）の人物を <image{i+1}> の人物に
- NOMARK[k](pos, face) 丸なし。pos は position_words() の位置の言葉（文に書く対象の順）
- 構文 0 が基本形（推論時の推奨）。face=True は顔アップ向けに服の言及を控えめにした文

このアプリで足したもの（学習データには無い文。英語）:

- 「A の服装のまま」（keep）… 枠ごとに、B の服を使わず A の服装（着ている量も含む）を保つ。
  全員が keep のときはテンプレートの「B から受け継ぐもの」から outfit design を外し、
  末尾に服装を保つ文を足す。一部だけ keep のときはテンプレートはそのままで、該当する人物に
  ついての例外の文を足す。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal, Sequence

# 丸の色（markers.MARK_COLORS と同じ。丸1=赤, 丸2=青, 丸3=緑, 丸4=橙）
COLOR_EN = {1: "red", 2: "blue", 3: "green", 4: "orange"}
ORDINAL_EN = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}


# --------------------------------------------------------------------------- テンプレート（学習時の写し）
def _clauses(items: list[str]) -> str:
    """'A, and B' / 'A, B, and C'（文中で対象ごとの句を並べる）。"""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _identity(face: bool, keep: bool = False) -> str:
    """置換後の人物が参照画像から受け継ぐもの。顔アップでは服を控えめに。keep は服を受け継がない。"""
    if keep:
        return "face, hairstyle, hair color, and eyes"
    if face:
        return "face, hairstyle, hair color, and eyes (and the design of any visible clothing)"
    return "face, hairstyle, hair color, eyes, and outfit design"


def _follow(face: bool, keep: bool = False) -> str:
    """<image1> に従うもの（ポーズ・服の状態）。keep は服そのものも <image1> に従う。"""
    if face:
        return "the head pose"
    return "the pose and the clothing" if keep else "the pose and the state of the clothing"


def _verb(face: bool, verb: str, keep: bool = False) -> str:
    """_follow(face) を主語にした動詞（単数 / 複数）。"""
    return f"{_follow(face, keep)} {verb + 's' if face else verb}"


def _ref(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _en_m0(n: int, face: bool = False, keep: bool = False) -> str:
    tg = [f"the person circled in {COLOR_EN[i]} (marker {i})" + (" in <image1>" if i == 1 else "")
          + f" with the person from <image{i + 1}>" for i in range(1, n + 1)]
    return ("Replace " + _clauses(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person", "Each new person") + f" should have the {_identity(face, keep)} of the person in "
            + _ref(n, "<image2>", "their reference image") + f", while {_verb(face, 'follow', keep)} <image1>. "
            "Do not use the art style of " + _ref(n, "<image2>", "the reference images") + "; draw "
            + _ref(n, "the new person", "the new people") + " in the art style of <image1>. "
            "Leave everyone else in <image1> unchanged, and remove the "
            + _ref(n, "circle and number", "circles and numbers") + " from the output.")


def _en_m1(n: int, face: bool = False, keep: bool = False) -> str:
    tg = [f"the person marked {i} ({COLOR_EN[i]} circle) with the character in <image{i + 1}>" for i in range(1, n + 1)]
    return ("In <image1>, swap " + _clauses(tg) + ". "
            "Match the pose, facial expression, composition, background, and art style to <image1>. "
            + _ref(n, "Give the swapped-in character", "Give each swapped-in character") + f" the {_identity(face, keep)} from "
            + _ref(n, "<image2>", "their reference image") + f", but keep {_follow(face, keep)} from <image1>. "
            "Render in the art style of <image1>, not that of " + _ref(n, "<image2>", "the reference images") + ". "
            "Do not change anyone else, and erase the " + _ref(n, "circle and number", "circles and numbers") + ".")


def _en_m2(n: int, face: bool = False, keep: bool = False) -> str:
    tg = [f"{COLOR_EN[i]} circle (marker {i}) -> the person from <image{i + 1}>" for i in range(1, n + 1)]
    return (_ref(n, "Swap the circled person in <image1>: ", "Swap the circled people in <image1>: ") + "; ".join(tg) + ". "
            "Preserve the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person takes", "Each new person takes") + f" the {_identity(face, keep)} from "
            + _ref(n, "the reference image", "their reference image") + f", while {_verb(face, 'come', keep)} from <image1>. "
            "Use the art style of <image1>, not the art style of " + _ref(n, "the reference image", "the reference images") + ". "
            "Keep everyone else unchanged. Do not leave the " + _ref(n, "circle or number", "circles or numbers")
            + " in the output.")


def _en_m3(n: int, face: bool = False, keep: bool = False) -> str:
    tg = [f"marker {i} ({COLOR_EN[i]}) becomes the person from <image{i + 1}>" for i in range(1, n + 1)]
    return (_ref(n, "Replace the circled person in <image1>: ", "Replace the circled people in <image1>: ") + "; ".join(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            f"Take the {_identity(face, keep)} from " + _ref(n, "the person in <image2>", "each reference person")
            + f", but keep {_follow(face, keep)} from <image1>. "
            "Draw in the art style of <image1> instead of the style of " + _ref(n, "<image2>", "the reference images") + ". "
            "Everyone else stays the same. Do not draw the " + _ref(n, "circle or number", "circles or numbers") + ".")


def _en_n0(pos: list[str], face: bool = False, keep: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} with the person from <image{i + 2}>" for i, p in enumerate(pos)]
    return ("In <image1>, replace " + _clauses(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person", "Each new person") + f" should have the {_identity(face, keep)} of the person in "
            + _ref(n, "<image2>", "their reference image") + f", while {_verb(face, 'follow', keep)} <image1>. "
            "Do not use the art style of " + _ref(n, "<image2>", "the reference images") + "; draw "
            + _ref(n, "the new person", "the new people") + " in the art style of <image1>. "
            "Leave everyone else in <image1> unchanged.")


def _en_n1(pos: list[str], face: bool = False, keep: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} with the character in <image{i + 2}>" for i, p in enumerate(pos)]
    return ("Using <image1> as the base, swap " + _clauses(tg) + ". "
            "Match the pose, facial expression, composition, background, and art style to <image1>. "
            + _ref(n, "Give the swapped-in character", "Give each swapped-in character") + f" the {_identity(face, keep)} from "
            + _ref(n, "<image2>", "their reference image") + f", but keep {_follow(face, keep)} from <image1>. "
            "Render in the art style of <image1>, not that of " + _ref(n, "<image2>", "the reference images") + ". "
            "Do not change anyone else.")


def _en_n2(pos: list[str], face: bool = False, keep: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} -> the person from <image{i + 2}>" for i, p in enumerate(pos)]
    return (_ref(n, "Swap this person in <image1>: ", "Swap these people in <image1>: ") + "; ".join(tg) + ". "
            "Preserve the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person takes", "Each new person takes") + f" the {_identity(face, keep)} from "
            + _ref(n, "the reference image", "their reference image") + f", while {_verb(face, 'come', keep)} from <image1>. "
            "Use the art style of <image1>, not the art style of " + _ref(n, "the reference image", "the reference images") + ". "
            "Keep everyone else unchanged.")


MARKED = [_en_m0, _en_m1, _en_m2, _en_m3]
NOMARK = [_en_n0, _en_n1, _en_n2]


# --------------------------------------------------------------------------- 位置の言葉（学習時の写し）
POS = {"only": "the person", "left": "the person on the left", "right": "the person on the right",
       "middle": "the person in the middle", "center": "the person in the center",
       "leftmost": "the leftmost person", "rightmost": "the rightmost person",
       "kth": lambda k: f"the {ORDINAL_EN[k]} person from the left"}


def position_words(all_chars: list[dict], target_chars: list[str], rng: random.Random | None = None) -> list[str]:
    """左から並べた順位を言葉にする（1 人なら「the person」）。4 人以上の両端は 2 通りから選ぶ。

    all_chars は ``{"char": 名前, "bbox_px": [x0, y0, x1, y1]}`` のリスト（学習時と同じ形）。
    rng を渡さなければ random モジュール（学習時と同じ乱数の使い方）。
    """
    choice = (rng or random).choice
    w = POS
    order = sorted(all_chars, key=lambda c: (c["bbox_px"][0] + c["bbox_px"][2]) / 2)
    n = len(order)
    out = []
    for tc in target_chars:
        k = [c["char"] for c in order].index(tc) + 1
        if n == 1:
            out.append(w["only"])
        elif n == 2:
            out.append(w["left"] if k == 1 else w["right"])
        elif n == 3:
            out.append({1: w["left"], 2: w["middle"], 3: w["right"]}[k])
        else:
            if k == 1:
                out.append(choice([w["kth"](1), w["leftmost"]]))
            elif k == n:
                out.append(choice([w["kth"](n), w["rightmost"]]))
            else:
                out.append(w["kth"](k))
    return out


def face_position(others_visible: bool) -> list[str]:
    """顔アップの丸なし: 他の人物が写っていれば「中央の人物」、いなければ「人物」。"""
    return [POS["center"] if others_visible else POS["only"]]


# --------------------------------------------------------------------------- このアプリの組み立て
Outfit = Literal["b", "a"]
Mode = Literal["marked", "position"]


@dataclass
class TargetSpec:
    """置き換える 1 人（枠番号 = リストの順 + 1）。"""

    box: Sequence[float]          # A 上の人物の枠 [x0, y0, x1, y1]（px）
    outfit: Outfit = "b"           # b = B の服を着せる / a = A の服装のまま


def _keep_sentence(who: list[str], refs: list[str], all_keep: bool) -> str:
    """「A の服装のまま」の枠についての文。"""
    n = len(who)
    if all_keep:
        head = "Keep the outfit of " + _clauses(who) + " exactly as it is in <image1>"
    else:
        head = "However, for " + _clauses(who) + ", keep the outfit exactly as it is in <image1>"
    return (head + ", including how much of the body is covered (even if "
            + _ref(n, "the person is", "they are") + " partially or fully unclothed); "
            "do not use the clothing from " + _clauses(refs) + ".")


def build_instruction(
    targets: list[TargetSpec],
    mode: Mode = "marked",
    face: bool = False,
    others: list[Sequence[float]] | None = None,
    template: int = 0,
    rng: random.Random | None = None,
) -> str:
    """枠の並び（枠 i → <image{i+1}>）から英語の指示文を作る。

    - mode="marked": 丸あり（A_marked を送る）。
    - mode="position": 丸なし（A を送る）。位置の言葉は targets と others（置き換えない人物の枠）の
      横方向の中心で並べた順位から作る。
    - 全員が「B の服」なら学習時のテンプレートそのまま。
    """
    n = len(targets)
    if not 1 <= n <= 4:
        raise ValueError("置き換える人物は 1〜4 人にしてください")
    keep_idx = [i for i, t in enumerate(targets) if t.outfit == "a"]
    all_keep = len(keep_idx) == n

    if mode == "marked":
        fn = MARKED[template % len(MARKED)]
        text = fn(n, face, all_keep) if all_keep else fn(n, face)
        who = [f"the person circled in {COLOR_EN[i + 1]} (marker {i + 1})" for i in keep_idx]
    else:
        others = others or []
        if face and n == 1:
            pos = face_position(bool(others))
        else:
            chars = [{"char": f"t{i}", "bbox_px": list(t.box)} for i, t in enumerate(targets)]
            chars += [{"char": f"o{i}", "bbox_px": list(b)} for i, b in enumerate(others)]
            pos = position_words(chars, [f"t{i}" for i in range(n)], rng)
        fn = NOMARK[template % len(NOMARK)]
        text = fn(pos, face, all_keep) if all_keep else fn(pos, face)
        who = [pos[i] for i in keep_idx]

    if keep_idx:
        refs = [f"<image{i + 2}>" for i in keep_idx]
        text += " " + _keep_sentence(who, refs, all_keep)
    return text


def is_face_closeup(box: Sequence[float], width: int, height: int, face_box: Sequence[float] | None = None) -> bool:
    """顔アップか。

    - 顔の枠が分かるとき: 顔の高さが人物の枠の高さの 40% 以上（顔・首元までしか写っていない）。
    - 分からないとき: 人物の枠が画像の 60% 以上を占める。
    画面で「自動 / 顔アップ / 通常」を切り替えられるので、迷う構図はそちらで直す。
    """
    x0, y0, x1, y1 = box
    bw, bh = max(x1 - x0, 1), max(y1 - y0, 1)
    if face_box is not None:
        return (face_box[3] - face_box[1]) >= 0.4 * bh
    return bw * bh >= 0.6 * width * height
