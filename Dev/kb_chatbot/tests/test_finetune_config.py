import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune import finetune_config as fc

def test_paths_are_under_state_dir_finetune():
    from Dev.kb_chatbot import config
    assert fc.DATA_DIR == config.STATE_DIR / "finetune"
    assert fc.TRAIN_JSONL.parent == fc.DATA_DIR and fc.TRAIN_JSONL.name == "train.jsonl"

def test_fits_8gb_config():
    assert fc.MICRO_BATCH == 1 and fc.SEQ_LEN in (1024, 2048)
    assert 0 < fc.LORA_R <= 32 and fc.BASE_MODEL_HF == "Qwen/Qwen2.5-3B-Instruct"
    assert fc.TUNED_TAG == "contoso-reasoning-qwen25-7b:v1"
