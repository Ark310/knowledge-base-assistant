"""procctl — maps low/normal/high onto app + Chrome-children priority classes."""
from types import SimpleNamespace

import scraper.app_settings as app_settings
from scraper.procctl import PRIORITY_LEVELS, apply_priority


class _FakeProc:
    def __init__(self, pid, name, children=None):
        self.pid = pid
        self._name = name
        self._children = children or []
        self.set_to = None
    def name(self):
        return self._name
    def children(self, recursive=False):
        return self._children
    def nice(self, value):
        self.set_to = value


def _fake_psutil(app):
    return SimpleNamespace(
        Process=lambda pid=None: app,
        BELOW_NORMAL_PRIORITY_CLASS="BELOW", NORMAL_PRIORITY_CLASS="NORM",
        ABOVE_NORMAL_PRIORITY_CLASS="ABOVE", HIGH_PRIORITY_CLASS="HIGH",
        NoSuchProcess=KeyError, AccessDenied=PermissionError,
    )


def test_high_maps_app_high_chrome_above_normal():
    kids = [_FakeProc(2, "chrome.exe"), _FakeProc(3, "conhost.exe")]
    app = _FakeProc(1, "python.exe", kids)
    touched = apply_priority("high", psutil_mod=_fake_psutil(app))
    assert app.set_to == "HIGH"
    assert kids[0].set_to == "ABOVE"       # chrome capped at ABOVE_NORMAL
    assert kids[1].set_to is None          # non-chrome child untouched
    assert touched == 2


def test_low_and_normal_apply_to_app_and_chrome():
    kid = _FakeProc(2, "chrome.exe")
    app = _FakeProc(1, "python.exe", [kid])
    apply_priority("low", psutil_mod=_fake_psutil(app))
    assert (app.set_to, kid.set_to) == ("BELOW", "BELOW")
    apply_priority("normal", psutil_mod=_fake_psutil(app))


def test_bad_level_and_dead_children_are_safe():
    class _Dying(_FakeProc):
        def nice(self, value):
            raise KeyError("gone")
    app = _FakeProc(1, "python.exe", [_Dying(2, "chrome.exe")])
    assert apply_priority("bogus", psutil_mod=_fake_psutil(app)) == 0
    assert apply_priority("high", psutil_mod=_fake_psutil(app)) == 1   # app only


def test_priority_setting_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "_file", lambda: tmp_path / "app_settings.json")
    assert app_settings.priority() == "normal"          # default
    app_settings.set_priority("high")
    assert app_settings.priority() == "high"
    app_settings.set_priority("bogus")
    assert app_settings.priority() == "normal"          # invalid falls back
