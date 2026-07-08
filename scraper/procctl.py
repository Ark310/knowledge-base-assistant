"""Process priority control (v4.0.3) — replaces the operator's Task-Manager dance.

Maps low/normal/high onto Windows priority classes for the app process and its
Chrome children. "high" gives the APP HIGH but Chrome only ABOVE_NORMAL — full
HIGH on a dozen Chrome processes can starve the desktop. psutil `nice(value)` on
Windows takes a priority CLASS constant. Re-applied periodically by the GUI while
a run is active so freshly-spawned Chrome processes pick the level up too.
Never raises: any failure is swallowed per-process; returns processes touched.
"""
from __future__ import annotations

PRIORITY_LEVELS = ("low", "normal", "high")


def _classes(ps, level: str):
    """(app_class, chrome_class) for a level, or None for unknown levels."""
    try:
        table = {
            "low":    (ps.BELOW_NORMAL_PRIORITY_CLASS, ps.BELOW_NORMAL_PRIORITY_CLASS),
            "normal": (ps.NORMAL_PRIORITY_CLASS,       ps.NORMAL_PRIORITY_CLASS),
            "high":   (ps.HIGH_PRIORITY_CLASS,         ps.ABOVE_NORMAL_PRIORITY_CLASS),
        }
    except AttributeError:      # non-Windows psutil: no priority classes
        return None
    return table.get(level)


def apply_priority(level: str, psutil_mod=None) -> int:
    if psutil_mod is None:
        try:
            import psutil as psutil_mod
        except Exception:
            return 0
    pair = _classes(psutil_mod, level)
    if pair is None:
        return 0
    app_class, chrome_class = pair
    touched = 0
    try:
        app = psutil_mod.Process()
        app.nice(app_class)
        touched += 1
        for p in app.children(recursive=True):
            try:
                if "chrome" in (p.name() or "").lower():
                    p.nice(chrome_class)
                    touched += 1
            except Exception:
                continue
    except Exception:
        pass
    return touched
