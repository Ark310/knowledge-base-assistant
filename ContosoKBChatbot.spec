# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import re as _re
_cfg_src = open("Dev/kb_chatbot/config.py", encoding="utf-8").read()
_vm = _re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _cfg_src)
VERSION = _vm.group(1) if _vm else "0.0"

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6", "sentence_transformers", "chromadb", "claude_agent_sdk", "markdown"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Drop the SDK's bundled claude CLI (~234 MB) — app will use the user's real claude.exe
datas = [(s, d) for (s, d) in datas if "_bundled" not in str(s).replace("\\", "/")]
binaries = [(s, d) for (s, d) in binaries if "_bundled" not in str(s).replace("\\", "/")]

hiddenimports += [
    "torch", "transformers", "tokenizers",
    "sklearn.utils._cython_blas",
]

# Bundle ONLY the two HF models this app uses so it works offline.
# (NOT the whole ~/.cache/huggingface — that also holds the v3-beta bge rerankers,
# ~3.2 GB we don't need.) At runtime HF_HOME points at <bundle>/models/huggingface
# (sys._MEIPASS-relative — PyInstaller onedir places datas under _internal/).
import os as _os
_hf = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface")
_WANT = ("models--cross-encoder--ms-marco-MiniLM-L-6-v2",
         "models--sentence-transformers--all-MiniLM-L6-v2")
_hub = _os.path.join(_hf, "hub")
if _os.path.isdir(_hub):
    for _model in _WANT:
        _mdir = _os.path.join(_hub, _model)
        if not _os.path.isdir(_mdir):
            continue
        for _root, _dirs, _files in _os.walk(_mdir):
            for _f in _files:
                _full = _os.path.join(_root, _f)
                _rel = _os.path.relpath(_full, _hf)   # e.g. hub/models--.../snapshots/...
                datas.append((_full, _os.path.join("models", "huggingface", _os.path.dirname(_rel))))

a = Analysis(
    ["Dev/kb_chatbot/gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # NOTE: do NOT exclude torch submodules — torch imports them eagerly
        # at startup (e.g. torch.utils.data.dataloader imports torch.distributed
        # unconditionally on line 25). Only torchvision/torchaudio are safe to
        # exclude because they are separate packages, not torch submodules.
        "torchvision", "torchaudio",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f"ContosoKBChatbot-v{VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name=f"ContosoKBChatbot-v{VERSION}",
)
