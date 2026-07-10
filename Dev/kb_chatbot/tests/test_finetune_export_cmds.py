import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.merge_and_export import gguf_convert_cmd, quantize_cmd

def test_convert_cmd_points_at_converter_and_merged_dir():
    cmd = gguf_convert_cmd(Path("m"), Path("out.gguf"), Path("llama.cpp"))
    assert any("convert_hf_to_gguf.py" in c for c in cmd)
    assert "m" in cmd[-1] or any(c.endswith("m") for c in cmd)

def test_quantize_cmd_uses_q4_k_m():
    cmd = quantize_cmd(Path("f16.gguf"), Path("q4.gguf"), Path("llama.cpp"))
    assert "Q4_K_M" in cmd
