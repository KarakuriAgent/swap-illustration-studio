"""テスト共通: データの置き場を一時フォルダにする。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    from app import jobs, model_setup

    monkeypatch.setenv("SWAP_DATA_DIR", str(tmp_path / "data"))
    for k in ("COMFY_MODELS_DIR", "COMFY_OUTPUT_DIR", "COMFY_INPUT_DIR", "ACCESS_TOKEN", "SWAP_BIND_HOST",
              "REQUIRE_TOKEN", "COMFY_CLOUD_API_KEY", "HF_TOKEN", "LORA_HF_REPO", "LORA_SHA256", "COMFY_URL"):
        monkeypatch.delenv(k, raising=False)
    model_setup._state.clear()
    model_setup._tasks.clear()
    jobs.manager.jobs.clear()
    yield tmp_path / "data"
    jobs.manager.jobs.clear()
