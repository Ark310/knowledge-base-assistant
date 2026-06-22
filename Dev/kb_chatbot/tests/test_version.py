import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_app_version_is_2_9_2():
    assert config.APP_VERSION == "2.9.2"
