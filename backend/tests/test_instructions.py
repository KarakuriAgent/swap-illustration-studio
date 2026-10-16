"""指示文が学習時のテンプレート（reference/instructions_ref.py）と同じ文面になること。"""

from __future__ import annotations

import random

import pytest

from app import instructions as I
from tests.reference import instructions_ref as R

POS_SETS = [
    ["the person"],
    ["the person on the left", "the person on the right"],
    ["the leftmost person", "the third person from the left", "the rightmost person"],
    ["the first person from the left", "the second person from the left", "the third person from the left",
     "the fourth person from the left"],
]


@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("face", [False, True])
def test_marked_templates_match_training(n, face):
    for k in range(4):
        assert I.MARKED[k](n, face) == R.MARKED["en"][k](n, face)


@pytest.mark.parametrize("pos", POS_SETS)
@pytest.mark.parametrize("face", [False, True])
def test_nomark_templates_match_training(pos, face):
    for k in range(3):
        assert I.NOMARK[k](pos, face) == R.NOMARK["en"][k](pos, face)


def test_build_instruction_default_is_basic_form():
    targets = [I.TargetSpec([0, 0, 10, 10]), I.TargetSpec([20, 0, 30, 10])]
    assert I.build_instruction(targets) == R.marked_instruction(2, "en")
    assert I.build_instruction(targets[:1], face=True) == R.marked_instruction(1, "en", face=True)
    for k in range(4):
        assert I.build_instruction(targets, template=k) == R.MARKED["en"][k](2, False)


def _chars(xs):
    return [{"char": f"c{i}", "bbox_px": [x, 0, x + 10, 10]} for i, x in enumerate(xs)]


@pytest.mark.parametrize("xs", [[5], [50, 5], [40, 0, 80], [0, 30, 60, 90], [90, 70, 50, 30, 10]])
def test_position_words_match_training(xs):
    chars = _chars(xs)
    names = [c["char"] for c in chars]
    for seed in range(5):
        random.seed(seed)
        ref = R.position_words(chars, names, "en")
        random.seed(seed)
        ours = I.position_words(chars, names)
        assert ours == ref
        ours2 = I.position_words(chars, names, random.Random(seed))
        random.seed(seed)
        assert ours2 == R.position_words(chars, names, "en")


def test_position_rules():
    rng = random.Random(0)
    assert I.position_words(_chars([0]), ["c0"], rng) == ["the person"]
    assert I.position_words(_chars([50, 0]), ["c0", "c1"], rng) == ["the person on the right", "the person on the left"]
    assert I.position_words(_chars([0, 30, 60]), ["c1"], rng) == ["the person in the middle"]
    w = I.position_words(_chars([0, 30, 60, 90]), ["c0", "c1", "c3"], rng)
    assert w[0] in ("the leftmost person", "the first person from the left")
    assert w[1] == "the second person from the left"
    assert w[2] in ("the rightmost person", "the fourth person from the left")
    assert I.face_position(True) == R.face_position(True) == ["the person in the center"]
    assert I.face_position(False) == ["the person"]


def test_position_mode_uses_others_for_order():
    # 対象 1 人 + 置き換えない人 1 人（右側）→ the person on the left
    t = [I.TargetSpec([0, 0, 10, 10])]
    text = I.build_instruction(t, mode="position", others=[[50, 0, 60, 10]])
    assert text == R.NOMARK["en"][0](["the person on the left"], False)
    # 対象 2 人を「右の人 → 枠 1」「左の人 → 枠 2」の順で指定すると、文もその順（<image2> = 右の人）
    t2 = [I.TargetSpec([50, 0, 60, 10]), I.TargetSpec([0, 0, 10, 10])]
    assert I.build_instruction(t2, mode="position") == R.NOMARK["en"][0](
        ["the person on the right", "the person on the left"], False)
    # 顔アップ・1 人・他の人がいる → the person in the center
    face = I.build_instruction(t, mode="position", face=True, others=[[50, 0, 60, 10]])
    assert face == R.NOMARK["en"][0](["the person in the center"], True)


def test_keep_outfit_all():
    t = [I.TargetSpec([0, 0, 10, 10], "a")]
    text = I.build_instruction(t)
    assert "outfit design" not in text
    assert "face, hairstyle, hair color, and eyes of the person in <image2>" in text
    assert "while the pose and the clothing follow <image1>" in text
    assert text.endswith("Keep the outfit of the person circled in red (marker 1) exactly as it is in <image1>, "
                         "including how much of the body is covered (even if the person is partially or fully "
                         "unclothed); do not use the clothing from <image2>.")


def test_keep_outfit_mixed_keeps_training_text():
    t = [I.TargetSpec([0, 0, 10, 10], "b"), I.TargetSpec([20, 0, 30, 10], "a")]
    text = I.build_instruction(t)
    base = R.marked_instruction(2, "en")
    assert text.startswith(base + " ")
    assert "However, for the person circled in blue (marker 2), keep the outfit exactly as it is in <image1>" in text
    assert text.endswith("do not use the clothing from <image3>.")


def test_keep_outfit_position():
    t = [I.TargetSpec([0, 0, 10, 10], "a"), I.TargetSpec([20, 0, 30, 10], "a")]
    text = I.build_instruction(t, mode="position")
    assert "Keep the outfit of the person on the left, and the person on the right exactly as it is" in text
    assert "(even if they are partially or fully unclothed)" in text
    assert "do not use the clothing from <image2>, and <image3>." in text


def test_target_count_limits():
    with pytest.raises(ValueError):
        I.build_instruction([])
    with pytest.raises(ValueError):
        I.build_instruction([I.TargetSpec([0, 0, 1, 1])] * 5)


def test_face_closeup():
    assert I.is_face_closeup([0, 0, 100, 100], 100, 100)                  # 画像のほぼ全部
    assert not I.is_face_closeup([0, 0, 30, 100], 100, 100)               # 細い全身
    assert I.is_face_closeup([0, 0, 50, 100], 200, 200, [10, 0, 40, 45])   # 顔が枠の 45%
    assert not I.is_face_closeup([0, 0, 50, 100], 100, 100, [10, 0, 30, 20])
