# reference/

`instructions_ref.py` は LoRA の学習データを作ったスクリプト（qwen-swap-lora の `scripts/instructions.py`）の
**無改変の写し**です。`tests/test_instructions.py` が、アプリの指示文（`app/instructions.py`）が学習時と
一字一句同じ文面になっていることを、これと突き合わせて確かめます。アプリからは import しません。
