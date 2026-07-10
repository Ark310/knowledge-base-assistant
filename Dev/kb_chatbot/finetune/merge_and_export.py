"""Merge the LoRA adapter into fp16, convert to GGUF, quantize Q4_K_M for Ollama.
The command builders are pure (unit-tested); main() is operator-run on the AI PC
(needs a llama.cpp checkout)."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
from Dev.kb_chatbot.finetune import finetune_config as fc

def gguf_convert_cmd(merged_dir: Path, out_gguf: Path, llama_cpp_dir: Path) -> list[str]:
    return [sys.executable, str(Path(llama_cpp_dir) / "convert_hf_to_gguf.py"),
            str(merged_dir), "--outfile", str(out_gguf), "--outtype", "f16"]

def quantize_cmd(f16_gguf: Path, out_gguf: Path, llama_cpp_dir: Path, qtype: str = "Q4_K_M") -> list[str]:
    exe = Path(llama_cpp_dir) / ("llama-quantize.exe" if sys.platform == "win32" else "llama-quantize")
    return [str(exe), str(f16_gguf), str(out_gguf), qtype]

def main(argv=None) -> None:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    ap = argparse.ArgumentParser()
    ap.add_argument("--llama-cpp", required=True, help="path to a llama.cpp checkout")
    args = ap.parse_args(argv)
    base = AutoModelForCausalLM.from_pretrained(fc.BASE_MODEL_HF, torch_dtype="auto")
    merged = PeftModel.from_pretrained(base, str(fc.ADAPTER_DIR)).merge_and_unload()
    fc.MERGED_DIR.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(fc.MERGED_DIR))
    AutoTokenizer.from_pretrained(str(fc.ADAPTER_DIR)).save_pretrained(str(fc.MERGED_DIR))
    f16 = fc.DATA_DIR / "merged-f16.gguf"
    subprocess.run(gguf_convert_cmd(fc.MERGED_DIR, f16, Path(args.llama_cpp)), check=True)
    subprocess.run(quantize_cmd(f16, fc.GGUF_PATH, Path(args.llama_cpp)), check=True)
    print(f"GGUF -> {fc.GGUF_PATH}")

if __name__ == "__main__":
    main()
