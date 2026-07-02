"""ResourceSampler — psutil-backed system/app/Chrome sampling, fully fake-injectable."""
from types import SimpleNamespace

from scraper.resmon import ResourceSampler, ResourceSnapshot


class _FakeProc:
    def __init__(self, pid, name, rss, children=None):
        self.pid = pid
        self._name = name
        self._rss = rss
        self._children = children or []
    def name(self):
        return self._name
    def memory_info(self):
        return SimpleNamespace(rss=self._rss)
    def children(self, recursive=False):
        return self._children


def _fake_psutil(children):
    app = _FakeProc(100, "python.exe", 200 * 1024 * 1024, children)
    return SimpleNamespace(
        cpu_percent=lambda interval=None: 42.5,
        virtual_memory=lambda: SimpleNamespace(
            total=16 * 1024**3, used=8 * 1024**3, available=8 * 1024**3),
        Process=lambda pid=None: app,
        NoSuchProcess=KeyError, AccessDenied=PermissionError,
    )


def test_sample_reports_system_and_app():
    s = ResourceSampler(psutil_mod=_fake_psutil([]))
    snap = s.sample()
    assert isinstance(snap, ResourceSnapshot)
    assert snap.cpu_pct == 42.5
    assert snap.ram_total_mb == 16 * 1024
    assert snap.ram_free_mb == 8 * 1024
    assert snap.app_rss_mb == 200


def test_sample_rolls_up_chrome_children_only():
    kids = [_FakeProc(201, "chrome.exe", 300 * 1024 * 1024),
            _FakeProc(202, "chrome.exe", 100 * 1024 * 1024),
            _FakeProc(203, "conhost.exe", 50 * 1024 * 1024)]
    s = ResourceSampler(psutil_mod=_fake_psutil(kids))
    snap = s.sample()
    assert snap.chrome_procs == [(201, 300), (202, 100)]
    assert snap.chrome_total_mb == 400
    assert s.chrome_pids() == [201, 202]


def test_sample_survives_dying_processes():
    class _Dying(_FakeProc):
        def memory_info(self):
            raise KeyError("gone")   # NoSuchProcess in the fake
    kids = [_Dying(201, "chrome.exe", 0), _FakeProc(202, "chrome.exe", 100 * 1024 * 1024)]
    s = ResourceSampler(psutil_mod=_fake_psutil(kids))
    snap = s.sample()   # must not raise
    assert snap.chrome_procs == [(202, 100)]
