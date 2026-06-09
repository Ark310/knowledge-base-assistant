# -*- mode: python ; coding: utf-8 -*-
# BETA build: separate exe name, bundles model weights + synonyms data.
# Never reuse for the stable build — the stable spec is ContosoKBChatbot.spec.
from PyInstaller.utils.hooks import collect_all
from huggingface_hub import snapshot_download

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6", "sentence_transformers", "chromadb", "claude_agent_sdk", "markdown"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += [
    "torch", "transformers", "tokenizers",
    "sklearn.utils._cython_blas",
    "rank_bm25",
]

# Bundle model snapshots from the local HF cache (must be pre-downloaded — the
# Task 10 reranker benchmark already did that). local_files_only keeps the build
# offline and fails loudly if a model is missing rather than silently fetching.
import sys as _sys
_sys.path.insert(0, ".")
from Dev.kb_chatbot.config import _EMBED_REPO, RERANKER_MODEL_REPO
for repo in (_EMBED_REPO, RERANKER_MODEL_REPO):
    snap = snapshot_download(repo, local_files_only=True)
    datas.append((snap, "models/" + repo.replace("/", "--")))

# Synonyms + any future bundled data → resolved at runtime via config.DATA_DIR
datas.append(("Dev/kb_chatbot/data", "kb_chatbot_data"))

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
        # at startup. Only torchvision/torchaudio are separate packages safe to drop.
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
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ContosoKBChatbot-BETA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
