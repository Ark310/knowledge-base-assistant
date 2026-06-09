import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_beta_constants():
    assert config.IS_BETA is True
    assert config.APP_VERSION == "3.0.0-beta"
    assert config.window_title() == "Contoso KB Chatbot — v3.0 BETA"


def test_frozen_state_dir_name_is_beta():
    # The frozen branch must derive its state dir from STATE_DIR_NAME
    assert config.STATE_DIR_NAME == "chatbot_state_beta"


def test_dev_state_dir_unchanged():
    # Non-frozen (test) runs keep using Dev/kb_chatbot/state — never the beta dir
    assert config.STATE_DIR.name == "state"
