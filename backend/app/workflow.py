"""ComfyUI に投げる API 形式のワークフローを組み立てる。

雛形は Karakuri Media Studio の workflow/image/qwen-image/qwen_image_21_edit(_turbo).json の写し
（app/workflows/ に同梱）。

- 参照画像は TextEncodeQwenImage21 の ``images.image_N`` に順に繋ぐ。``image_1`` = A（編集キャンバス、
  出力の縦横比もこれに従う）、``image_2`` 以降 = B1, B2, …（指示文の <image2>, <image3>, … と一致）
- LoRA は UNETLoader（"1"）と QwenImage21Cache（"4"）の間に LoraLoaderModelOnly（"20"）を挿す
  （qwen-swap-lora/scripts/round1/eval_lora.py の with_lora と同じ）
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

WF_DIR = Path(__file__).resolve().parent / "workflows"
ModelKind = Literal["turbo", "base"]

WORKFLOW_FILES: dict[str, str] = {
    "turbo": "qwen_image_21_edit_turbo.json",
    "base": "qwen_image_21_edit.json",
}

#: モデルを読むノードの種類 -> (入力名, ComfyUI の models 配下のフォルダ)
LOADER_FOLDERS: dict[str, tuple[str, str]] = {
    "UNETLoader": ("unet_name", "diffusion_models"),
    "CLIPLoader": ("clip_name", "text_encoders"),
    "VAELoader": ("vae_name", "vae"),
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
}

LORA_NODE_ID = "20"
OUTPUT_PREFIX = "swap_studio/out"


@lru_cache(maxsize=None)
def _template(kind: str) -> str:
    return (WF_DIR / WORKFLOW_FILES[kind]).read_text(encoding="utf-8")


def load_template(kind: ModelKind) -> dict:
    """雛形（毎回新しいコピー）。"""
    return json.loads(_template(kind))


def with_lora(graph: dict, lora: str, strength: float) -> dict:
    """UNETLoader -> LoraLoaderModelOnly -> QwenImage21Cache に繋ぎ替える。"""
    graph[LORA_NODE_ID] = {"class_type": "LoraLoaderModelOnly",
                           "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": strength},
                           "_meta": {"title": "LoRA（anime-swap）"}}
    graph["4"]["inputs"]["model"] = [LORA_NODE_ID, 0]
    return graph


def build_edit(
    prompt: str,
    images: list[str],
    seed: int,
    kind: ModelKind = "turbo",
    lora: str | None = None,
    strength: float = 1.0,
    resolution: int = 1024,
    prefix: str = OUTPUT_PREFIX,
) -> dict:
    """images = ComfyUI にアップロード済みのファイル名（A, B1, B2, … の順）。

    strength が 0 以下、または lora が空なら LoRA を挿さない（素のモデル）。
    """
    if not images:
        raise ValueError("画像がありません")
    g = load_template(kind)
    tmpl = g.pop("0")
    enc = g["5"]["inputs"]
    enc.pop("images.image_1", None)
    for i, name in enumerate(images, start=1):
        nid = f"100{i}"
        node = copy.deepcopy(tmpl)
        node["inputs"]["image"] = name
        node["_meta"] = {"title": "A（編集キャンバス）" if i == 1 else f"B{i - 1}"}
        g[nid] = node
        enc[f"images.image_{i}"] = [nid, 0]
    enc["prompt"] = prompt
    enc["resolution"] = resolution
    g["6"]["inputs"]["seed"] = int(seed)
    g["8"]["inputs"]["filename_prefix"] = prefix
    if lora and strength > 0:
        with_lora(g, lora, float(strength))
    return g


def required_models(kind: ModelKind) -> list[dict]:
    """雛形が読むモデルファイル（LoRA は設定で決まるので含めない）。

    戻り値: ``[{"class_type", "field", "folder", "filename"}]``
    """
    out = []
    for node in load_template(kind).values():
        ct = node.get("class_type")
        if ct in LOADER_FOLDERS:
            field, folder = LOADER_FOLDERS[ct]
            name = node["inputs"].get(field)
            if isinstance(name, str) and name:
                out.append({"class_type": ct, "field": field, "folder": folder, "filename": name})
    return out
