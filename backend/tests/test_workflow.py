"""ワークフローの組み立て。"""

from __future__ import annotations

from app.workflow import build_edit, required_models


def test_build_edit_turbo_with_lora():
    g = build_edit("PROMPT", ["swap/A.png", "swap/B1.png", "swap/B2.png"], 11, "turbo",
                   "qwen-image-21/anime-swap.safetensors", 1.0)
    assert "0" not in g   # 雛形の LoadImage は消える
    enc = g["5"]["inputs"]
    assert enc["prompt"] == "PROMPT"
    assert enc["resolution"] == 1024
    # image_1 = A, image_2.. = B（<imageN> と一致）
    for i, name in enumerate(["swap/A.png", "swap/B1.png", "swap/B2.png"], start=1):
        nid = enc[f"images.image_{i}"][0]
        assert g[nid]["class_type"] == "LoadImage"
        assert g[nid]["inputs"]["image"] == name
    assert "images.image_4" not in enc
    # LoRA: UNETLoader("1") -> LoraLoaderModelOnly("20") -> QwenImage21Cache("4")
    assert g["20"]["class_type"] == "LoraLoaderModelOnly"
    assert g["20"]["inputs"] == {"model": ["1", 0], "lora_name": "qwen-image-21/anime-swap.safetensors",
                                 "strength_model": 1.0}
    assert g["4"]["class_type"] == "QwenImage21Cache"
    assert g["4"]["inputs"]["model"] == ["20", 0]
    assert g["1"]["inputs"]["unet_name"] == "qwen_image_2.1_turbo_int8_convrot.safetensors"
    assert g["6"]["inputs"]["seed"] == 11
    assert g["6"]["inputs"]["steps"] == 8
    assert g["6"]["inputs"]["model"] == ["4", 0]
    assert g["8"]["inputs"]["filename_prefix"] == "swap_studio/out"


def test_build_edit_base_without_lora():
    g = build_edit("P", ["a.png", "b.png"], 5, "base", "x.safetensors", 0.0)
    assert "20" not in g
    assert g["4"]["inputs"]["model"] == ["1", 0]
    assert g["1"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert g["6"]["inputs"]["steps"] == 25


def test_templates_are_not_mutated():
    build_edit("P", ["a.png"], 1, "turbo", "l.safetensors", 0.5)
    g = build_edit("Q", ["a.png"], 2, "turbo")
    assert "20" not in g and g["4"]["inputs"]["model"] == ["1", 0]


def test_required_models():
    t = {(m["folder"], m["filename"]) for m in required_models("turbo")}
    assert t == {("diffusion_models", "qwen_image_2.1_turbo_int8_convrot.safetensors"),
                 ("text_encoders", "qwen3vl_8b_int8_convrot.safetensors"),
                 ("vae", "qwen_image_2.1_vae_bf16.safetensors")}
    b = {m["filename"] for m in required_models("base")}
    assert "qwen_image_2.1_int8_convrot.safetensors" in b
