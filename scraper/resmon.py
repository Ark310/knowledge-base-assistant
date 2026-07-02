"""psutil-backed resource sampler for auto-tune + the GUI monitor panel (v4.0.3).

Injectable psutil so tests never touch the real system. Sampling must NEVER
throw: a process that dies mid-iteration is skipped (NoSuchProcess/AccessDenied),
and any systemic psutil failure yields a zeroed snapshot — monitoring can't be
allowed to take down a run.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ResourceSnapshot:
    cpu_pct: float = 0.0
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    ram_free_mb: int = 0
    app_rss_mb: int = 0
    chrome_procs: list = field(default_factory=list)   # [(pid, rss_mb)]
    chrome_total_mb: int = 0


_MB = 1024 * 1024


class ResourceSampler:
    def __init__(self, psutil_mod=None):
        if psutil_mod is None:
            import psutil as psutil_mod   # lazy: keeps import cost off app startup
        self._ps = psutil_mod
        self._app = self._ps.Process()

    def _chrome_children(self):
        try:
            kids = self._app.children(recursive=True)
        except Exception:
            return []
        out = []
        for p in kids:
            try:
                if "chrome" in (p.name() or "").lower():
                    out.append(p)
            except Exception:
                continue
        return out

    def chrome_pids(self) -> list[int]:
        return [p.pid for p in self._chrome_children()]

    def sample(self) -> ResourceSnapshot:
        snap = ResourceSnapshot()
        try:
            snap.cpu_pct = float(self._ps.cpu_percent(interval=None))
            vm = self._ps.virtual_memory()
            snap.ram_total_mb = int(vm.total // _MB)
            snap.ram_used_mb = int(vm.used // _MB)
            snap.ram_free_mb = int(vm.available // _MB)
            snap.app_rss_mb = int(self._app.memory_info().rss // _MB)
        except Exception:
            return snap
        for p in self._chrome_children():
            try:
                snap.chrome_procs.append((p.pid, int(p.memory_info().rss // _MB)))
            except Exception:
                continue
        snap.chrome_total_mb = sum(m for _, m in snap.chrome_procs)
        return snap
