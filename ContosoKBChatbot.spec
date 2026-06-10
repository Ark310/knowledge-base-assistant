# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

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

# Bundle the HF model cache so the app works offline.
# HF_HOME is set to <exedir>/models/huggingface at runtime (see gui.py top).
# The user's cache lives at ~/.cache/huggingface/; bundle its contents under
# models/huggingface/ so that HF_HOME=<exedir>/models/huggingface finds hub/.
import os as _os
_hf = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface")
if _os.path.isdir(_hf):
    for _root, _dirs, _files in _os.walk(_hf):
        for _f in _files:
            _full = _os.path.join(_root, _f)
            _rel = _os.path.relpath(_full, _hf)
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
    name="ContosoKBChatbot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="ContosoKBChatbot",
)
