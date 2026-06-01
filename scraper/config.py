from pathlib import Path
import sys

# ── Paths ─────────────────────────────────────────────────────────────────────
# When frozen as a PyInstaller exe, __file__ points inside a temp extract dir;
# library/state must sit next to the executable instead.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    STATE_DIR = BASE_DIR / "state"
else:
    BASE_DIR = Path(__file__).parent.parent           # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"
LIBRARY_BASE = BASE_DIR / "library"
STATE_FILE   = STATE_DIR / "scraped_versions.json"
LOG_FILE     = STATE_DIR / "run.log"
REPORT_FILE  = STATE_DIR / "last_run_report.json"

BASE_URL = "https://help.contoso.example"

# ── Products ──────────────────────────────────────────────────────────────────
# space_key values verified live on 2026-05-27. release_notes_url is derived as
# f"{BASE_URL}/display/{space_key}". The --discover command can re-derive and
# rewrite release_notes_url robustly, but these defaults work out of the box.
PRODUCTS: dict[str, dict] = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "space_key": "releasenotes",
        "release_notes_url": "https://help.contoso.example/display/releasenotes",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
    "web4": {
        "display_name": "Web4",
        "space_key": "ReleaseNotesWeb4",
        "release_notes_url": "https://help.contoso.example/display/ReleaseNotesWeb4",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
    "saleshub": {
        "display_name": "SalesHub",
        "space_key": "SHReleaseNotes",
        "release_notes_url": "https://help.contoso.example/display/SHReleaseNotes",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
}

# Canonical column normalization for release-note tables.
# Keys are lowercased, whitespace-collapsed header text. The Risk column header
# is a long blob beginning "risk assessment" and is matched by prefix in code.
COLUMN_SYNONYMS: dict[str, str] = {
    "sr. #": "sno", "sr #": "sno", "sr.#": "sno", "s.no": "sno", "sno": "sno", "#": "sno", "no": "sno",
    "task id": "id", "tfs/portal id": "id", "portal/tfs id": "id", "tfs id": "id", "portal id": "id", "id": "id",
    "module": "module",
    "new feature/ improvement of current feature": "feature_type",
    "prerequisites": "prerequisites",
    "details": "details", "description": "details",
    "configuration changes": "config_changes",
    "key feature": "key_feature", "key features": "key_feature",
    "is there a change to previous behavior?": "behavior_change",
    "is there a change to previous behaviour?": "behavior_change",
    "is this feature 'on' by default?": "on_by_default",
}
