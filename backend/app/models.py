"""API の入出力の型（pydantic）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Box = list[float]


def _check_box(v: Box) -> Box:
    if len(v) != 4:
        raise ValueError("枠は [x0, y0, x1, y1] の 4 つの数で指定してください")
    x0, y0, x1, y1 = v
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


class TargetIn(BaseModel):
    """置き換える 1 人。リストの順が枠番号（1〜4）。"""

    box: Box
    ref: int = Field(ge=0, le=3, description="refs の何番目の B を入れるか")
    outfit: Literal["b", "a"] = "b"

    _box = field_validator("box")(_check_box)


class OtherIn(BaseModel):
    """置き換えない人物（位置の言葉・丸が他人の顔にかかるかの判定に使う）。"""

    box: Box

    _box = field_validator("box")(_check_box)


class GenSettings(BaseModel):
    target: Literal["local", "cloud"] | None = None   # None = 設定の実行先
    model: Literal["turbo", "base"] = "turbo"
    lora_name: str | None = None                       # None = 設定の LoRA 名
    strength: float = Field(default=1.0, ge=0.0, le=1.5)
    seed: int | None = Field(default=None, ge=0, le=2**53)   # None = ランダム
    count: int = Field(default=1, ge=1, le=4)


class SceneSpec(BaseModel):
    """指示文と A_marked を作るのに要る情報（生成・プレビュー共通）。"""

    scene_id: str
    targets: list[TargetIn] = Field(min_length=1, max_length=4)
    others: list[OtherIn] = Field(default_factory=list, max_length=16)
    faces: list[Box] = Field(default_factory=list, max_length=32)
    mode: Literal["marked", "position"] = "marked"
    face_mode: Literal["auto", "on", "off"] = "auto"
    template: int = Field(default=0, ge=0, le=3)

    @field_validator("faces")
    @classmethod
    def _faces(cls, v: list[Box]) -> list[Box]:
        return [_check_box(b) for b in v]


class GenerateRequest(SceneSpec):
    refs: list[str] = Field(min_length=1, max_length=4)
    prompt_override: str | None = Field(default=None, max_length=8000)
    settings: GenSettings = Field(default_factory=GenSettings)


class RerunRequest(BaseModel):
    seed: int | None = Field(default=None, ge=0, le=2**53)
    strength: float | None = Field(default=None, ge=0.0, le=1.5)
    count: int | None = Field(default=None, ge=1, le=4)
    model: Literal["turbo", "base"] | None = None


class CropRequest(BaseModel):
    box: Box

    _box = field_validator("box")(_check_box)


class DetectRequest(BaseModel):
    image_id: str


class LoginRequest(BaseModel):
    token: str
