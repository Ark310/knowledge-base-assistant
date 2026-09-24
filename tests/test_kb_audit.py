"""kb_audit — discovered-vs-on-disk verification. Pure; discovery injected."""
import json
from pathlib import Path

from scraper.kb_audit import audit_spaces

CFG_A = {"space_key": "SA", "display_name": "SysAdmin", "product": "tradedesk", "lib_folder": "system_administration"}
CFG_B = {"space_key": "howto", "display_name": "How To's", "product": "web2", "lib_folder": "how_to"}


def _art(title, slug):
    return {"title": title, "url": f"https://kb/x/{slug}", "page_id": "1", "slug": slug}


def _write(base: Path, cfg, slug):
    d = base / cfg["product"] / cfg["lib_folder"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps({"title": slug}), encoding="utf-8")


def test_audit_flags_missing_articles(tmp_path):
    def discover(key):
        return [_art("On Disk", "on_disk"), _art("Lost One", "lost_one")]
    _write(tmp_path, CFG_A, "on_disk")
    res = audit_spaces([CFG_A], tmp_path, discover=discover)
    sa = res["spaces"]["SA"]
    assert (sa["discovered"], sa["on_disk"]) == (2, 1)
    assert [m["slug"] for m in sa["missing"]] == ["lost_one"]
    assert sa["missing"][0]["space_key"] == "SA"
    assert res["totals"] == {"discovered": 2, "on_disk": 1, "missing": 1, "spaces_with_errors": 0}


def test_audit_clean_space_has_no_missing(tmp_path):
    def discover(key):
        return [_art("A", "a")]
    _write(tmp_path, CFG_A, "a")
    res = audit_spaces([CFG_A], tmp_path, discover=discover)
    assert res["spaces"]["SA"]["missing"] == []
    assert res["totals"]["missing"] == 0


def test_audit_survives_discovery_failure_and_marks_error(tmp_path):
    def discover(key):
        if key == "SA":
            raise RuntimeError("confluence down")
        return [_art("B", "b")]
    _write(tmp_path, CFG_B, "b")
    res = audit_spaces([CFG_A, CFG_B], tmp_path, discover=discover)
    assert res["spaces"]["SA"]["error"] == "RuntimeError"       # TYPE only, no message
    assert res["spaces"]["howto"]["error"] is None
    assert res["totals"]["spaces_with_errors"] == 1


def test_audit_empty_space_is_clean_not_error(tmp_path):
    res = audit_spaces([CFG_A], tmp_path, discover=lambda key: [])
    assert res["spaces"]["SA"] == {"display_name": "SysAdmin", "discovered": 0,
                                   "on_disk": 0, "missing": [], "error": None}
