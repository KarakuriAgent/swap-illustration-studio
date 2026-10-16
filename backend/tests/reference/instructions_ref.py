"""LoRA 学習用の指示文（prompt）のテンプレート。既定は英語（推論時は LLM が英語のプロンプトで操作するため）。

<image1> = 編集キャンバス A（丸あり A_marked または丸なし A）、<image2> 以降 = 参照人物 B1, B2, …（edit_image の順、
ComfyUI の image_1, image_2, … の順）。

- MARKED[lang][k](n, face=False)   丸あり。丸 i（1=赤, 2=青, 3=緑, 4=橙）の人物を <image{i+1}> の人物に
- NOMARK[lang][k](pos, face=False) 丸なし。pos は position_words() の位置の言葉のリスト（左から並べた順位）
- MARKED[lang][0] が基本形（元のシーンの指示文 build_instruction と同じ）
- face=True は顔アップ（face・face_xl）向け。服の言及を控えめにする（英語のみ。日本語版は元のまま区別なし）
- 日本語版（lang="ja"）は第一弾で最初に使った文面。検証（英語版と対象・番号・位置の対応が一致するか）のために残す

乱数: 呼び出し側は random.choice(MARKED[lang]) / random.choice(NOMARK[lang]) で選ぶ。英語版と日本語版はテンプレートの数が
同じ（丸あり 4・丸なし 3）で、k 番目どうしが同じ構文の対訳なので、同じシードなら同じサンプルに同じ番号の構文が選ばれ、
乱数の進み方（クロップの種類などほかの選択）も変わらない。position_words も言語によらず同じ回数だけ乱数を使う。
"""
from __future__ import annotations

import random

LANGS = ("en", "ja")

# 丸の色（postprocess.draw_marks の MARK_COLORS と同じ。丸1=赤, 丸2=青, 丸3=緑, 丸4=橙）
COLOR_EN = {1: "red", 2: "blue", 3: "green", 4: "orange"}
COLOR_JA = {1: "赤い丸", 2: "青い丸", 3: "緑の丸", 4: "橙色の丸"}
CIRCLED_JA = {1: "丸1", 2: "丸2", 3: "丸3", 4: "丸4"}
ORDINAL_EN = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}


# --------------------------------------------------------------------------- 英語
def _clauses(items: list[str]) -> str:
    """'A, and B' / 'A, B, and C'（文中で対象ごとの句を並べる）。"""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _identity(face: bool) -> str:
    """置換後の人物が参照画像から受け継ぐもの。顔アップでは服を控えめに。"""
    if face:
        return "face, hairstyle, hair color, and eyes (and the design of any visible clothing)"
    return "face, hairstyle, hair color, eyes, and outfit design"


def _follow(face: bool) -> str:
    """<image1> に従うもの（ポーズ・服の状態）。"""
    return "the head pose" if face else "the pose and the state of the clothing"


def _verb(face: bool, verb: str) -> str:
    """_follow(face) を主語にした動詞（単数 / 複数）。"""
    return f"{_follow(face)} {verb + 's' if face else verb}"


def _ref(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _en_m0(n: int, face: bool = False) -> str:
    tg = [f"the person circled in {COLOR_EN[i]} (marker {i})" + (" in <image1>" if i == 1 else "")
          + f" with the person from <image{i + 1}>" for i in range(1, n + 1)]
    return ("Replace " + _clauses(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person", "Each new person") + f" should have the {_identity(face)} of the person in "
            + _ref(n, "<image2>", "their reference image") + f", while {_verb(face, 'follow')} <image1>. "
            "Do not use the art style of " + _ref(n, "<image2>", "the reference images") + "; draw "
            + _ref(n, "the new person", "the new people") + " in the art style of <image1>. "
            "Leave everyone else in <image1> unchanged, and remove the "
            + _ref(n, "circle and number", "circles and numbers") + " from the output.")


def _en_m1(n: int, face: bool = False) -> str:
    tg = [f"the person marked {i} ({COLOR_EN[i]} circle) with the character in <image{i + 1}>" for i in range(1, n + 1)]
    return ("In <image1>, swap " + _clauses(tg) + ". "
            "Match the pose, facial expression, composition, background, and art style to <image1>. "
            + _ref(n, "Give the swapped-in character", "Give each swapped-in character") + f" the {_identity(face)} from "
            + _ref(n, "<image2>", "their reference image") + f", but keep {_follow(face)} from <image1>. "
            "Render in the art style of <image1>, not that of " + _ref(n, "<image2>", "the reference images") + ". "
            "Do not change anyone else, and erase the " + _ref(n, "circle and number", "circles and numbers") + ".")


def _en_m2(n: int, face: bool = False) -> str:
    tg = [f"{COLOR_EN[i]} circle (marker {i}) -> the person from <image{i + 1}>" for i in range(1, n + 1)]
    return (_ref(n, "Swap the circled person in <image1>: ", "Swap the circled people in <image1>: ") + "; ".join(tg) + ". "
            "Preserve the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person takes", "Each new person takes") + f" the {_identity(face)} from "
            + _ref(n, "the reference image", "their reference image") + f", while {_verb(face, 'come')} from <image1>. "
            "Use the art style of <image1>, not the art style of " + _ref(n, "the reference image", "the reference images") + ". "
            "Keep everyone else unchanged. Do not leave the " + _ref(n, "circle or number", "circles or numbers")
            + " in the output.")


def _en_m3(n: int, face: bool = False) -> str:
    tg = [f"marker {i} ({COLOR_EN[i]}) becomes the person from <image{i + 1}>" for i in range(1, n + 1)]
    return (_ref(n, "Replace the circled person in <image1>: ", "Replace the circled people in <image1>: ") + "; ".join(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            f"Take the {_identity(face)} from " + _ref(n, "the person in <image2>", "each reference person")
            + f", but keep {_follow(face)} from <image1>. "
            "Draw in the art style of <image1> instead of the style of " + _ref(n, "<image2>", "the reference images") + ". "
            "Everyone else stays the same. Do not draw the " + _ref(n, "circle or number", "circles or numbers") + ".")


def _en_n0(pos: list[str], face: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} with the person from <image{i + 2}>" for i, p in enumerate(pos)]
    return ("In <image1>, replace " + _clauses(tg) + ". "
            "Keep the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person", "Each new person") + f" should have the {_identity(face)} of the person in "
            + _ref(n, "<image2>", "their reference image") + f", while {_verb(face, 'follow')} <image1>. "
            "Do not use the art style of " + _ref(n, "<image2>", "the reference images") + "; draw "
            + _ref(n, "the new person", "the new people") + " in the art style of <image1>. "
            "Leave everyone else in <image1> unchanged.")


def _en_n1(pos: list[str], face: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} with the character in <image{i + 2}>" for i, p in enumerate(pos)]
    return ("Using <image1> as the base, swap " + _clauses(tg) + ". "
            "Match the pose, facial expression, composition, background, and art style to <image1>. "
            + _ref(n, "Give the swapped-in character", "Give each swapped-in character") + f" the {_identity(face)} from "
            + _ref(n, "<image2>", "their reference image") + f", but keep {_follow(face)} from <image1>. "
            "Render in the art style of <image1>, not that of " + _ref(n, "<image2>", "the reference images") + ". "
            "Do not change anyone else.")


def _en_n2(pos: list[str], face: bool = False) -> str:
    n = len(pos)
    tg = [f"{p} -> the person from <image{i + 2}>" for i, p in enumerate(pos)]
    return (_ref(n, "Swap this person in <image1>: ", "Swap these people in <image1>: ") + "; ".join(tg) + ". "
            "Preserve the pose, facial expression, composition, background, and art style of <image1>. "
            + _ref(n, "The new person takes", "Each new person takes") + f" the {_identity(face)} from "
            + _ref(n, "the reference image", "their reference image") + f", while {_verb(face, 'come')} from <image1>. "
            "Use the art style of <image1>, not the art style of " + _ref(n, "the reference image", "the reference images") + ". "
            "Keep everyone else unchanged.")


# --------------------------------------------------------------------------- 日本語（第一弾で最初に使った文面。face は無視）
def _ja_m0(n: int, face: bool = False) -> str:
    return ("<image1>の" + "、".join(f"{CIRCLED_JA[i]}の人物を<image{i + 1}>の人物に" for i in range(1, n + 1))
            + "置き換える。ポーズ・表情・画風は<image1>のまま、服のデザインは"
            + ("<image2>の人物" if n == 1 else "各人物") + "のものにする。丸は消す")


def _ja_m1(n: int, face: bool = False) -> str:
    return ("<image1>で" + "、".join(f"{CIRCLED_JA[i]}で囲まれた人物を<image{i + 1}>の人物" for i in range(1, n + 1))
            + "に差し替えてください。ポーズと表情と絵柄は<image1>に合わせ、服は"
            + ("<image2>" if n == 1 else "それぞれの参照画像") + "のデザインにして、丸と番号は消してください。")


def _ja_m2(n: int, face: bool = False) -> str:
    return ("、".join(f"{COLOR_JA[i]}（{i}番）の人物→<image{i + 1}>" for i in range(1, n + 1))
            + "の人物に入れ替え。<image1>のポーズ・表情・画風を保ち、服は参照画像の人物のデザインに。丸と番号は残さない")


def _ja_m3(n: int, face: bool = False) -> str:
    return ("<image1>の丸で示した人物を置き換える：" + "、".join(f"丸{i}は<image{i + 1}>" for i in range(1, n + 1))
            + "。体勢・表情・タッチは<image1>のまま、服装は"
            + ("<image2>" if n == 1 else "各参照") + "の人物の服にする。丸は描かない")


def _ja_n0(pos: list[str], face: bool = False) -> str:
    return ("<image1>の" + "、".join(f"{p}を<image{i + 2}>の人物に" for i, p in enumerate(pos))
            + "置き換える。ポーズ・表情・画風は<image1>のまま、服のデザインは"
            + ("<image2>の人物" if len(pos) == 1 else "各人物") + "のものにする")


def _ja_n1(pos: list[str], face: bool = False) -> str:
    return ("<image1>の" + "、".join(f"{p}を<image{i + 2}>の人物" for i, p in enumerate(pos))
            + "に差し替えてください。ポーズと表情と絵柄は<image1>に合わせ、服は"
            + ("<image2>" if len(pos) == 1 else "それぞれの参照画像") + "のデザインにしてください。")


def _ja_n2(pos: list[str], face: bool = False) -> str:
    return ("、".join(f"<image1>の{p}→<image{i + 2}>" for i, p in enumerate(pos))
            + "の人物に入れ替え。<image1>のポーズ・表情・画風を保ち、服は参照画像の人物のデザインに")


MARKED = {"en": [_en_m0, _en_m1, _en_m2, _en_m3], "ja": [_ja_m0, _ja_m1, _ja_m2, _ja_m3]}
NOMARK = {"en": [_en_n0, _en_n1, _en_n2], "ja": [_ja_n0, _ja_n1, _ja_n2]}
assert all(len(MARKED[l]) == len(MARKED["en"]) and len(NOMARK[l]) == len(NOMARK["en"]) for l in LANGS)


def check_lang(lang: str) -> str:
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}: {lang!r}")
    return lang


def marked_instruction(n: int, lang: str = "en", face: bool = False) -> str:
    """基本形（丸あり、構文 0）。元のシーンの指示文（common.build_instruction）。"""
    return MARKED[check_lang(lang)][0](n, face)


# 位置の言葉（左から並べた順位）。日本語版と同じ規則・同じ乱数の使い方
POS = {
    "en": {"only": "the person", "left": "the person on the left", "right": "the person on the right",
           "middle": "the person in the middle", "center": "the person in the center",
           "leftmost": "the leftmost person", "rightmost": "the rightmost person",
           "kth": lambda k: f"the {ORDINAL_EN[k]} person from the left"},
    "ja": {"only": "人物", "left": "左の人物", "right": "右の人物", "middle": "真ん中の人物", "center": "中央の人物",
           "leftmost": "一番左の人物", "rightmost": "一番右の人物", "kth": lambda k: f"左から{k}番目の人物"},
}


def position_words(all_chars: list[dict], target_chars: list[str], lang: str = "en") -> list[str]:
    """左から並べた順位を言葉にする（1 人なら「the person」）。4 人以上の両端は 2 通りから random で選ぶ。"""
    w = POS[check_lang(lang)]
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
                out.append(random.choice([w["kth"](1), w["leftmost"]]))
            elif k == n:
                out.append(random.choice([w["kth"](n), w["rightmost"]]))
            else:
                out.append(w["kth"](k))
    return out


def face_position(others_visible: bool, lang: str = "en") -> list[str]:
    """顔アップの丸なし: 他の人物が写っていれば「中央の人物」、いなければ「人物」。"""
    w = POS[check_lang(lang)]
    return [w["center"] if others_visible else w["only"]]
