# KB Scraper v4.0.3 "Big Batch" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 30k-ticket unattended runs survive (auto-recovery, no mass-fail), explain themselves (popup alerts), run as fast as the machine allows (resource auto-tune + measured speed fixes), and give the operator live control + visibility (priority, workers, resource monitor).

**Architecture:** All changes sit on the proven v4.0.2 async engine (`scraper/ticket_engine_async.py`). New small modules: `resmon.py` (psutil sampler), `procctl.py` (process priority), `scrape_state.py` (batched state writes), `supervisor.py` (shared-browser recovery), `run_registry.py` (single-run guard). GUI work is confined to `ticket_tab.py` + `async_runner.py` + a new `resource_monitor.py` widget.

**Tech Stack:** Python 3.11, PySide6, Playwright async, psutil (NEW dependency), pytest (+pytest-asyncio pattern already used in tests/test_ticket_engine_async.py — plain `asyncio.run` in tests), PyInstaller one-folder.

**Spec:** `docs/superpowers/specs/2026-07-02-kb-scraper-v4.0.3-design.md`

## Global Constraints

- Log exception TYPES only, never messages (org policy — no PII/secrets in logs).
- Passwords: OS keyring only; never logged/persisted (unchanged paths — don't touch).
- Version string everywhere: `4.0.3`.
- Worker hard cap stays 10 (`_clamp_workers`, UI spinbox range).
- Build: fresh `--workpath build_v403`, one-folder, `--distpath dist` (OneDrive lock rule).
- NO exe build before a user-confirmed live smoke (standing rule, cerebrum).
- Run tests with: `scraper\venv\Scripts\python.exe -m pytest tests\ -x -q` from repo root.
- Suite is 260 green before this plan; keep it green every commit.
- Branch: `feat/kb-scraper-v4.0.3` (already created; spec committed).

---

### Task 1: ResourceSampler (`scraper/resmon.py`) + psutil dependency

**Files:**
- Create: `scraper/resmon.py`
- Modify: `scraper/requirements.txt` (add `psutil>=5.9.0`)
- Test: `tests/test_resmon.py`

**Interfaces:**
- Produces: `ResourceSnapshot` dataclass — fields `cpu_pct: float`, `ram_total_mb: int`, `ram_used_mb: int`, `ram_free_mb: int`, `app_rss_mb: int`, `chrome_procs: list[tuple[int, int]]` (pid, rss_mb), `chrome_total_mb: int`.
- Produces: `ResourceSampler(psutil_mod=None)` with `.sample() -> ResourceSnapshot` and `.chrome_pids() -> list[int]`. `psutil_mod=None` imports real psutil lazily; tests inject a fake.

- [ ] **Step 1: Install psutil into the venv and add to requirements**

```
scraper\venv\Scripts\python.exe -m pip install "psutil>=5.9.0"
```

Append `psutil>=5.9.0` to `scraper/requirements.txt`.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_resmon.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_resmon.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.resmon'`

- [ ] **Step 4: Implement `scraper/resmon.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_resmon.py -q`
Expected: 3 passed

- [ ] **Step 6: Full suite green, then commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\ -q`

```bash
git add scraper/resmon.py scraper/requirements.txt tests/test_resmon.py
git commit -m "feat(v4.0.3): ResourceSampler — psutil system/app/Chrome sampling"
```

---

### Task 2: Process priority control (`scraper/procctl.py`) + setting

**Files:**
- Create: `scraper/procctl.py`
- Modify: `scraper/app_settings.py` (persist priority)
- Test: `tests/test_procctl.py`

**Interfaces:**
- Consumes: `ResourceSampler.chrome_pids()` is NOT used — procctl enumerates children itself (keeps modules independent).
- Produces: `PRIORITY_LEVELS = ("low", "normal", "high")`; `apply_priority(level: str, psutil_mod=None) -> int` (returns processes touched, 0 on any systemic failure); `app_settings.priority() -> str` / `app_settings.set_priority(level: str)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_procctl.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_procctl.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.procctl'`

- [ ] **Step 3: Implement `scraper/procctl.py`**

```python
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
```

- [ ] **Step 4: Add priority persistence to `scraper/app_settings.py`**

Append after `set_headless`:

```python
_VALID_PRIORITIES = ("low", "normal", "high")

def priority() -> str:
    """Process priority while scraping (v4.0.3). Default 'normal'."""
    v = load().get("priority")
    return v if v in _VALID_PRIORITIES else "normal"

def set_priority(level: str) -> None:
    d = load()
    d["priority"] = level if level in _VALID_PRIORITIES else "normal"
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_procctl.py tests\test_app_settings.py -q` then `-m pytest tests\ -q`

```bash
git add scraper/procctl.py scraper/app_settings.py tests/test_procctl.py
git commit -m "feat(v4.0.3): process priority control (app + Chrome children) + setting"
```

---

### Task 3: AdaptiveGate v2 — resource tune + live ceiling

**Files:**
- Modify: `scraper/throttle.py`
- Test: `tests/test_throttle.py` (append)

**Interfaces:**
- Consumes: `ResourceSnapshot` fields `cpu_pct`, `ram_free_mb` (values only — no import needed).
- Produces: `AdaptiveGate.tune(cpu_pct: float, ram_free_mb: float) -> None` (pure, sync) and `AdaptiveGate.set_ceiling(n: int) -> None` (sync; engine's tuner task calls both from inside the loop). Constructor gains keyword `cpu_high=90.0, cpu_low=75.0, ram_low_mb=800.0, ram_ok_mb=1500.0`.

- [ ] **Step 1: Write failing tests (append to `tests/test_throttle.py`)**

```python
# ── v4.0.3: resource tune + live ceiling ─────────────────────────────────────

def test_tune_steps_down_on_high_cpu():
    g = AdaptiveGate(8)
    g.tune(cpu_pct=95.0, ram_free_mb=4000.0)
    assert g.permits == 7

def test_tune_steps_down_on_low_ram():
    g = AdaptiveGate(8)
    g.tune(cpu_pct=10.0, ram_free_mb=500.0)
    assert g.permits == 7

def test_tune_steps_up_with_headroom_but_never_past_ceiling():
    g = AdaptiveGate(8)
    g.permits = 4
    g.tune(cpu_pct=30.0, ram_free_mb=6000.0)
    assert g.permits == 5
    g.permits = 8
    g.tune(cpu_pct=30.0, ram_free_mb=6000.0)
    assert g.permits == 8

def test_tune_holds_in_dead_band():
    g = AdaptiveGate(8)
    g.permits = 5
    g.tune(cpu_pct=80.0, ram_free_mb=1000.0)   # between thresholds: no change
    assert g.permits == 5

def test_tune_respects_min_permits():
    g = AdaptiveGate(2)
    g.permits = 1
    g.tune(cpu_pct=99.0, ram_free_mb=100.0)
    assert g.permits == 1

def test_set_ceiling_lowers_and_raises_live():
    g = AdaptiveGate(8)
    g.set_ceiling(3)
    assert g.max_permits == 3 and g.permits == 3
    g.set_ceiling(6)
    assert g.max_permits == 6
    assert g.permits == 3          # permits climb back via tune/record, not instantly

def test_set_ceiling_clamps_to_at_least_one():
    g = AdaptiveGate(8)
    g.set_ceiling(0)
    assert g.max_permits == 1 and g.permits == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_throttle.py -q`
Expected: new tests FAIL — `AttributeError: 'AdaptiveGate' object has no attribute 'tune'`

- [ ] **Step 3: Implement in `scraper/throttle.py`**

Extend `__init__` signature (add before `backoff_base`): `cpu_high: float = 90.0, cpu_low: float = 75.0, ram_low_mb: float = 800.0, ram_ok_mb: float = 1500.0` and store them (`self.cpu_high, self.cpu_low, self.ram_low_mb, self.ram_ok_mb = cpu_high, cpu_low, ram_low_mb, ram_ok_mb`). Add methods after `record`:

```python
    def tune(self, cpu_pct: float, ram_free_mb: float) -> None:
        """Resource-aware step (v4.0.3): shrink under CPU/RAM pressure, grow toward
        the ceiling when there's clear headroom AND recent outcomes aren't failing.
        Pure + sync (called from the engine's tuner task inside the loop)."""
        if cpu_pct >= self.cpu_high or ram_free_mb <= self.ram_low_mb:
            if self.permits > self.min_permits:
                self.permits -= 1
        elif cpu_pct <= self.cpu_low and ram_free_mb >= self.ram_ok_mb:
            if self.permits < self.max_permits and self._fail_ratio() < self.down_at:
                self.permits += 1

    def set_ceiling(self, n: int) -> None:
        """Live worker-slider ceiling. Lowering clamps permits immediately; raising
        only lifts the ceiling — permits climb back via tune()/record()."""
        self.max_permits = max(1, int(n))
        self.min_permits = min(self.min_permits, self.max_permits)
        if self.permits > self.max_permits:
            self.permits = self.max_permits
```

Note: `acquire`'s `while self._inflight >= self.permits` re-checks on every notify, and `release` calls `notify_all`, so live changes take effect without extra wiring.

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_throttle.py -q` then `-m pytest tests\ -q`

```bash
git add scraper/throttle.py tests/test_throttle.py
git commit -m "feat(v4.0.3): AdaptiveGate resource tune + live ceiling"
```

---

### Task 4: Batched scrape-state writes (`scraper/scrape_state.py`)

**Files:**
- Create: `scraper/scrape_state.py`
- Modify: `scraper/ticket_engine_async.py` (use ScrapedState instead of `_load_scraped`/`_mark_scraped`)
- Test: `tests/test_scrape_state.py`

**Interfaces:**
- Consumes: `scraper.ticket_engine.TICKET_STATE_FILE` as the default path.
- Produces: `ScrapedState(state_file=None, *, every=25, interval=10.0, clock=time.monotonic)` with `.load() -> set[str]`, `.mark(tid: str) -> None`, `.flush() -> None`, `.ids: set[str]`. Journal lives next to the state file as `<name>.journal` (one tid per line, appended); `flush()` rewrites the JSON and truncates the journal; `load()` replays a leftover journal (crash recovery).
- The sync engine keeps its old `_mark_scraped` (unchanged, KB/legacy sync paths); only the async engine switches.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scrape_state.py
"""ScrapedState — batched writes + append-only journal so a hard kill loses nothing."""
import json

from scraper.scrape_state import ScrapedState


def _mk(tmp_path, **kw):
    return ScrapedState(state_file=tmp_path / "scraped_tickets.json", **kw)


def test_load_empty_then_mark_and_flush_roundtrip(tmp_path):
    st = _mk(tmp_path)
    assert st.load() == set()
    st.mark("101"); st.mark("102")
    st.flush()
    assert set(json.loads((tmp_path / "scraped_tickets.json").read_text())) == {"101", "102"}
    assert (tmp_path / "scraped_tickets.json.journal").read_text() == ""


def test_marks_are_journaled_not_rewritten_every_time(tmp_path):
    st = _mk(tmp_path, every=1000, interval=9999)
    st.load()
    for i in range(10):
        st.mark(str(i))
    assert not (tmp_path / "scraped_tickets.json").exists()          # no rewrite yet
    lines = (tmp_path / "scraped_tickets.json.journal").read_text().split()
    assert len(lines) == 10


def test_compacts_every_n_marks(tmp_path):
    st = _mk(tmp_path, every=3, interval=9999)
    st.load()
    st.mark("1"); st.mark("2")
    assert not (tmp_path / "scraped_tickets.json").exists()
    st.mark("3")                                                     # hits every=3
    assert set(json.loads((tmp_path / "scraped_tickets.json").read_text())) == {"1", "2", "3"}


def test_compacts_on_interval(tmp_path):
    now = [0.0]
    st = _mk(tmp_path, every=1000, interval=10.0, clock=lambda: now[0])
    st.load()
    st.mark("1")
    now[0] = 11.0
    st.mark("2")                                                     # interval elapsed
    assert set(json.loads((tmp_path / "scraped_tickets.json").read_text())) == {"1", "2"}


def test_load_replays_leftover_journal_after_crash(tmp_path):
    (tmp_path / "scraped_tickets.json").write_text(json.dumps(["1"]))
    (tmp_path / "scraped_tickets.json.journal").write_text("2\n3\n")
    st = _mk(tmp_path)
    assert st.load() == {"1", "2", "3"}
    # replay also compacts, so the recovered ids survive the next crash
    assert set(json.loads((tmp_path / "scraped_tickets.json").read_text())) == {"1", "2", "3"}


def test_corrupt_state_file_degrades_to_journal_only(tmp_path):
    (tmp_path / "scraped_tickets.json").write_text("{not json")
    (tmp_path / "scraped_tickets.json.journal").write_text("7\n")
    st = _mk(tmp_path)
    assert st.load() == {"7"}
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_scrape_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.scrape_state'`

- [ ] **Step 3: Implement `scraper/scrape_state.py`**

```python
"""Batched scraped-tickets state (v4.0.3).

v4.0.2 rewrote the full ~50KB OneDrive-synced scraped_tickets.json after EVERY
saved ticket. Now saves append one line to a `.journal` sidecar (cheap, atomic
enough) and the full JSON is compacted every `every` marks or `interval`
seconds, at flush(), and on journal replay after a crash — a hard kill loses
nothing (load() replays the journal).
"""
from __future__ import annotations
import json
import time
from pathlib import Path


class ScrapedState:
    def __init__(self, state_file: Path | None = None, *,
                 every: int = 25, interval: float = 10.0, clock=time.monotonic):
        if state_file is None:
            from scraper.ticket_engine import TICKET_STATE_FILE
            state_file = TICKET_STATE_FILE
        self._file = Path(state_file)
        self._journal = self._file.with_name(self._file.name + ".journal")
        self._every, self._interval, self._clock = max(1, every), interval, clock
        self.ids: set[str] = set()
        self._unflushed = 0
        self._last_compact = clock()

    def load(self) -> set[str]:
        ids: set[str] = set()
        try:
            if self._file.exists():
                ids = set(json.loads(self._file.read_text(encoding="utf-8")))
        except Exception:
            ids = set()
        replayed = False
        try:
            if self._journal.exists():
                extra = [ln for ln in self._journal.read_text(encoding="utf-8").split()
                         if ln.strip()]
                replayed = bool(extra)
                ids.update(extra)
        except Exception:
            pass
        self.ids = ids
        if replayed:
            self._compact()
        return self.ids

    def mark(self, tid: str) -> None:
        tid = str(tid)
        if tid in self.ids:
            return
        self.ids.add(tid)
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            with self._journal.open("a", encoding="utf-8") as f:
                f.write(tid + "\n")
        except Exception:
            pass
        self._unflushed += 1
        if (self._unflushed >= self._every
                or self._clock() - self._last_compact >= self._interval):
            self._compact()

    def flush(self) -> None:
        self._compact()

    def _compact(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(sorted(self.ids), indent=2),
                                  encoding="utf-8")
            self._journal.write_text("", encoding="utf-8")
        except Exception:
            return
        self._unflushed = 0
        self._last_compact = self._clock()
```

- [ ] **Step 4: Wire into the async engine**

In `scraper/ticket_engine_async.py`:
- Import: `from scraper.scrape_state import ScrapedState` (drop `_load_scraped, _mark_scraped` from the `scraper.ticket_engine` import — keep the rest).
- In `run_ticket_scrape_async`, replace `already = _load_scraped()` with:

```python
    scraped_state = ScrapedState()
    already = scraped_state.load()
```

- In the worker success path replace:

```python
                        async with state_lock:
                            _mark_scraped(tid); already.add(tid)
```

with:

```python
                        async with state_lock:
                            scraped_state.mark(tid); already.add(tid)
```

- In the engine's `finally:` block (before closing the shared browser) add:

```python
        try:
            scraped_state.flush()
        except Exception:
            pass
```

- [ ] **Step 5: Run new tests + the async engine suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_scrape_state.py tests\test_ticket_engine_async.py -q` then full suite.
(If `tests/test_ticket_engine_async.py` monkeypatches `_mark_scraped` on the async module, update those fixtures to monkeypatch `ScrapedState.mark`/`.load` instead — check with `grep -n "_mark_scraped\|_load_scraped" tests/test_ticket_engine_async.py`.)

```bash
git add scraper/scrape_state.py scraper/ticket_engine_async.py tests/
git commit -m "feat(v4.0.3): batched scraped-state writes + crash-safe journal"
```

---

### Task 5: BrowserSupervisor + engine auto-recovery (no more mass-fail)

**Files:**
- Create: `scraper/supervisor.py`
- Modify: `scraper/ticket_engine_async.py` (worker error path, breaker path, drain semantics)
- Modify: `scraper/ticket_engine.py` (add `on_alert` to `TicketEngineCallbacks`)
- Test: `tests/test_supervisor.py`, extend `tests/test_ticket_engine_async.py`

**Interfaces:**
- Consumes: `browser_factory() -> AsyncBrowser`-like (must have `.open() -> self`, `.new_page()`, `.close()`), `login_once(browser, username, password) -> bool`, `TicketEngineCallbacks`.
- Produces:

```python
class BrowserSupervisor:
    generation: int          # bumps on every successful recovery
    give_up: bool            # True after max_consecutive failed recoveries
    browser                  # current browser object (None before start)
    async def start(self) -> bool                       # initial open+login
    async def new_page(self)                            # page from current browser
    async def relogin(self) -> bool                     # re-auth on the CURRENT browser
    async def recover(self, seen_generation: int, reason: str) -> bool
    def reset_give_up(self) -> None                     # called on operator Resume
    async def close(self) -> None
```

- Produces: `TicketEngineCallbacks.on_alert: Callable[[str, str, str], None]` (severity `"warning"|"error"`, title, body) — default no-op.
- Engine behavior contract (relied on by Task 8 GUI): infra failure NEVER drains pending tickets; instead `control.pause()` + one `on_alert`. `drain_to_failed` fires only for startup login failure; cancel leaves the queue (existing behavior).

- [ ] **Step 1: Add `on_alert` to callbacks (tiny, no test churn)**

In `scraper/ticket_engine.py`, extend `TicketEngineCallbacks`:

```python
@dataclass
class TicketEngineCallbacks:
    on_log:         Callable[[str, str], None]        = field(default=lambda lvl, msg: None)
    on_progress:    Callable[[int, int], None]        = field(default=lambda i, n: None)
    on_ticket:      Callable[[str, str], None]        = field(default=lambda tid, st: None)
    on_finished:    Callable[[dict], None]            = field(default=lambda rep: None)
    on_ticket_meta: Callable[[str, str, int], None]   = field(default=lambda tid, title, nf: None)
    on_alert:       Callable[[str, str, str], None]   = field(default=lambda sev, title, body: None)
```

- [ ] **Step 2: Write failing supervisor tests**

```python
# tests/test_supervisor.py
"""BrowserSupervisor — single-flight shared-browser recovery with bounded give-up."""
import asyncio

from scraper.supervisor import BrowserSupervisor
from scraper.ticket_engine import TicketEngineCallbacks


class _FakeBrowser:
    def __init__(self, fail_open=False):
        self.fail_open = fail_open
        self.closed = False
        self.pages = 0
    async def open(self):
        if self.fail_open:
            raise RuntimeError("no chrome")
        return self
    async def new_page(self):
        self.pages += 1
        return object()
    async def close(self):
        self.closed = True


def _sup(factory_results, login_results=None, max_consecutive=3):
    """factory_results: list of _FakeBrowser to hand out in order.
    login_results: list of bools per login attempt (default all True)."""
    made = []
    def factory():
        b = factory_results[len(made)] if len(made) < len(factory_results) else _FakeBrowser()
        made.append(b)
        return b
    logins = login_results or []
    async def login_once(browser, u, p):
        return logins.pop(0) if logins else True
    alerts = []
    cb = TicketEngineCallbacks(on_alert=lambda s, t, b: alerts.append((s, t, b)))
    sup = BrowserSupervisor(factory, login_once, "u", "p", cb,
                            max_consecutive=max_consecutive)
    return sup, made, alerts


def test_start_opens_and_logs_in():
    sup, made, _ = _sup([_FakeBrowser()])
    assert asyncio.run(sup.start()) is True
    assert sup.browser is made[0] and sup.generation == 0


def test_recover_replaces_browser_and_bumps_generation():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        ok = await sup.recover(sup.generation, "browser dead")
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and sup.generation == 1
    assert made[0].closed is True and sup.browser is made[1]


def test_recover_is_single_flight_across_workers():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        gen = sup.generation
        results = await asyncio.gather(*(sup.recover(gen, "dead") for _ in range(5)))
        return sup, made, results
    sup, made, results = asyncio.run(main())
    assert all(results)
    assert sup.generation == 1          # ONE recovery, not five
    assert len(made) == 2               # start + one recovery


def test_gives_up_after_max_consecutive_failures_and_alerts_once():
    async def main():
        sup, _, alerts = _sup(
            [_FakeBrowser()] + [_FakeBrowser(fail_open=True)] * 5, max_consecutive=3)
        await sup.start()
        outs = []
        for _ in range(4):
            outs.append(await sup.recover(sup.generation, "dead"))
        return sup, alerts, outs
    sup, alerts, outs = asyncio.run(main())
    assert outs[:3] == [False, False, False] and sup.give_up is True
    assert outs[3] is False             # short-circuits once given up
    assert len(alerts) == 1             # exactly one popup, not four
    assert alerts[0][0] == "error"


def test_reset_give_up_allows_retry_after_resume():
    async def main():
        sup, _, _ = _sup([_FakeBrowser(), _FakeBrowser(fail_open=True),
                          _FakeBrowser(fail_open=True), _FakeBrowser(fail_open=True),
                          _FakeBrowser()], max_consecutive=3)
        await sup.start()
        for _ in range(3):
            await sup.recover(sup.generation, "dead")
        assert sup.give_up
        sup.reset_give_up()
        ok = await sup.recover(sup.generation, "retry after resume")
        return sup, ok
    sup, ok = asyncio.run(main())
    assert ok is True and sup.give_up is False and sup.generation == 1


def test_stale_generation_returns_immediately_without_restart():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        await sup.recover(0, "dead")            # real recovery -> gen 1
        ok = await sup.recover(0, "stale")      # caller saw gen 0: already fixed
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and sup.generation == 1 and len(made) == 2


def test_relogin_failure_falls_back_to_full_recover():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()],
                            login_results=[True, False, True])
        await sup.start()                        # login #1 True
        ok = await sup.relogin()                 # login #2 False -> full recover (login #3 True)
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and len(made) == 2 and sup.generation == 1
```

- [ ] **Step 3: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_supervisor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.supervisor'`

- [ ] **Step 4: Implement `scraper/supervisor.py`**

```python
"""Shared-browser supervisor (v4.0.3, bug-115/bug-116).

v4.0.2 light mode had ONE shared Chrome and no recovery path when IT died:
workers could only rebuild their tab (`shared_browser.new_page()` on a corpse),
so all of them exited and the engine mass-failed everything still queued
(2026-07-02: 28,620 tickets). The supervisor owns the shared browser and gives
workers a single-flight recovery: whoever hits the corpse first restarts
Chrome + re-logs-in while everyone else awaits the same lock, then all continue
on the new generation. Bounded: after `max_consecutive` failed recoveries it
sets give_up, emits ONE on_alert, and the engine pauses — pending tickets stay
queued for an operator Resume (reset_give_up + retry).

Logs exception TYPES only (org policy).
"""
from __future__ import annotations
import asyncio


class BrowserSupervisor:
    def __init__(self, browser_factory, login_once, username, password, cb, *,
                 max_consecutive: int = 3):
        self._factory = browser_factory
        self._login_once = login_once
        self._user, self._pw = username, password
        self._cb = cb
        self._max = max(1, max_consecutive)
        self._lock = asyncio.Lock()
        self._consecutive = 0
        self._alerted = False
        self.generation = 0
        self.give_up = False
        self.browser = None

    async def start(self) -> bool:
        try:
            self.browser = await self._factory().open()
            return bool(await self._login_once(self.browser, self._user, self._pw))
        except Exception as exc:
            self._cb.on_log("error", f"browser start failed ({type(exc).__name__}).")
            return False

    async def new_page(self):
        return await self.browser.new_page()

    async def relogin(self) -> bool:
        """Re-auth on the CURRENT browser (session expiry); full recover on failure."""
        async with self._lock:
            try:
                if await self._login_once(self.browser, self._user, self._pw):
                    self._consecutive = 0
                    return True
            except Exception:
                pass
        return await self.recover(self.generation, "session expired")

    async def recover(self, seen_generation: int, reason: str) -> bool:
        if self.give_up:
            return False
        async with self._lock:
            if self.generation != seen_generation:
                return True                     # someone else already recovered
            if self.give_up:
                return False
            self._cb.on_log("warning", f"shared browser recovery: {reason}")
            old, self.browser = self.browser, None
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            try:
                b = await self._factory().open()
                if not await self._login_once(b, self._user, self._pw):
                    raise RuntimeError("re-login failed")
            except Exception as exc:
                self._consecutive += 1
                self._cb.on_log("error",
                    f"browser recovery {self._consecutive}/{self._max} failed "
                    f"({type(exc).__name__}).")
                if self._consecutive >= self._max:
                    self.give_up = True
                    if not self._alerted:
                        self._alerted = True
                        self._cb.on_alert("error", "Scrape paused — browser unrecoverable",
                            "WHAT HAPPENED: Chrome crashed and could not be restarted "
                            f"after {self._max} attempts.\n"
                            "LIKELY CAUSE: out of memory or a network/portal outage.\n"
                            "WHAT IS PRESERVED: everything scraped so far is saved; "
                            "remaining tickets are still queued (nothing was failed).\n"
                            "WHAT TO DO: close other programs or lower Workers, then "
                            "press Resume to retry. Stop cancels the run.")
                return False
            self.browser = b
            self.generation += 1
            self._consecutive = 0
            self._cb.on_log("info", f"shared browser recovered (generation {self.generation}).")
            return True

    def reset_give_up(self) -> None:
        self.give_up = False
        self._alerted = False
        self._consecutive = 0

    async def close(self) -> None:
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass
```

- [ ] **Step 5: Run supervisor tests**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_supervisor.py -q`
Expected: 7 passed

- [ ] **Step 6: Rewire the engine worker loop (light mode) around the supervisor**

In `scraper/ticket_engine_async.py`:

1. Import: `from scraper.supervisor import BrowserSupervisor`.
2. Replace the shared-browser provisioning block:

```python
    supervisor = None
    if mode != "multi":
        supervisor = BrowserSupervisor(browser_factory, login_once, username, password, cb)
        if not await supervisor.start():
            cb.on_log("error", "Login failed; aborting.")
            cb.on_alert("error", "Login failed",
                "WHAT HAPPENED: the portal rejected the login (or the browser could "
                "not start).\nWHAT TO DO: check credentials in Settings and your "
                "network, then start the scrape again.")
            await drain_to_failed("(login failed)")
            await supervisor.close()
            cb.on_finished(stats)
            return stats
```

3. `_open_worker_page` light-mode line becomes `return None, await supervisor.new_page()`.
4. In the worker's `except Exception` block, replace the whole tear-down + rebuild-or-exit section (from `rebuilds += 1` through the `broke = True` rebuild-failure branch) with a recovery loop that NEVER exits on infra failure in light mode:

```python
                except Exception as exc:
                    if res_is_session_expired(exc) if False else False:
                        pass
                    if n < MAX_TICKET_ATTEMPTS:
                        cb.on_log("warning", f"{prefix}#{tid}: worker error ({type(exc).__name__}) "
                                             f"— redispatching ({n}/{MAX_TICKET_ATTEMPTS}).")
                        pending.put_nowait(tid)
                    else:
                        cb.on_log("error", f"{prefix}#{tid}: failed after {n} ({type(exc).__name__}).")
                        await terminal(tid, "failed", "failed")
                    rebuilds += 1
                    try:
                        if page is not None:
                            await page.close()
                    except Exception:
                        pass
                    page = None
                    since_recycle = 0
                    if own_browser is not None:            # multi mode: own browser
                        try:
                            await own_browser.close()
                        except Exception:
                            pass
                        own_browser = None
                    # Rebuild the page; if the SHARED browser is the corpse, run
                    # single-flight supervisor recovery instead of exiting (bug-116).
                    while page is None and not control.cancelled:
                        try:
                            own_browser, page = await _open_worker_page()
                            portal = page_portal_factory(page)
                        except Exception:
                            if supervisor is None:          # multi mode: bounded as before
                                if rebuilds > MAX_WORKER_REBUILDS:
                                    cb.on_log("error", f"{prefix}rebuild failed — worker exiting.")
                                    broke = True
                                break
                            gen = supervisor.generation
                            if not await supervisor.recover(gen, "worker page rebuild failed"):
                                if supervisor.give_up:
                                    control.pause()          # alert already emitted (once)
                                    await control.wait_if_paused_async()
                                    if control.cancelled:
                                        broke = True
                                        break
                                    supervisor.reset_give_up()   # operator resumed: retry
                                else:
                                    await asyncio.sleep(1.0)
```

   Then delete the old `if rebuilds > MAX_WORKER_REBUILDS: ... else: try: own_browser, page = ...` block entirely (the loop above replaces it). Also remove the stray first two lines (`if res_is_session_expired... pass`) — they are shown here only to anchor the replacement location; the final code starts at `if n < MAX_TICKET_ATTEMPTS:`.
5. Session-expiry: in the `try` body, replace `raise RuntimeError("session expired")` with:

```python
                    if res is _SESSION_EXPIRED:
                        cb.on_log("warning", f"{prefix}#{tid}: session expired")
                        pending.put_nowait(tid)
                        if supervisor is not None:
                            await supervisor.relogin()
                            portal = page_portal_factory(await supervisor.new_page()) \
                                if page is None else portal
                        else:
                            raise RuntimeError("session expired")
                        continue
```

   (Keep `ok = False` semantics: place this BEFORE `ok = True`; the `finally: await gate.release(ok)` still records a failure so the gate throttles. The redispatched tid is not double-counted: `attempts` was already bumped, which is acceptable — session expiry is rare after auto-relogin.)
6. Breaker + alert: extend the existing `gate.consume_trip()` block body to ALSO alert:

```python
                if gate.consume_trip():
                    cb.on_log("error",
                        f"{prefix}⚠ Sustained failures — run PAUSED. Check credentials/"
                        "network/portal; reduce workers or enable Headless in Settings, "
                        "then Resume.")
                    cb.on_alert("warning", "Scrape paused — sustained failures",
                        "WHAT HAPPENED: most recent tickets are failing even after "
                        "throttling down.\nLIKELY CAUSE: portal slowness, network "
                        "problems, or machine overload.\nWHAT IS PRESERVED: everything "
                        "scraped so far is saved; remaining tickets are still queued.\n"
                        "WHAT TO DO: check the portal in a browser, lower Workers, or "
                        "enable Headless in Settings — then press Resume.")
                    control.pause()
                    continue
```

7. After `await asyncio.gather(...)`: replace the unconditional `drain_to_failed("(not processed — all workers stopped)")` with:

```python
            if not control.cancelled:
                leftover = pending.qsize()
                if leftover:
                    # Workers can only all exit with work left in MULTI mode now.
                    cb.on_alert("error", "Scrape stopped early",
                        f"WHAT HAPPENED: all workers stopped with {leftover} tickets "
                        "unprocessed.\nWHAT IS PRESERVED: everything scraped so far is "
                        "saved.\nWHAT TO DO: restart the scrape for the remaining "
                        "tickets (already-scraped ones are skipped automatically).")
                    await drain_to_failed("(not processed — all workers stopped)")
```

8. Engine `finally:` — replace `if shared_browser is not None: await shared_browser.close()` with:

```python
        if supervisor is not None:
            await supervisor.close()
```

- [ ] **Step 7: Extend `tests/test_ticket_engine_async.py` with the collapse regression**

Follow the file's existing fake-browser/fake-portal fixtures (read them first: `grep -n "def \|class " tests/test_ticket_engine_async.py`). Add:

```python
def test_shared_browser_death_recovers_and_never_mass_fails():
    """bug-116 regression: shared browser dies mid-run -> supervisor recovery,
    run completes, zero mass-failed tickets, one recovery log."""
    # Arrange a browser whose new_page() raises RuntimeError after N pages
    # (simulating Chrome death), while the factory's NEXT browser works. Drive
    # run_ticket_scrape_async over ~6 tickets, workers=2, mode="light".
    # Assert: stats["failed"] == 0 and stats["saved"] == 6 and any
    # "shared browser recovered" in the captured log lines.

def test_supervisor_give_up_pauses_and_alerts_instead_of_draining():
    """Factory that ALWAYS fails after the first browser: engine must pause
    (control.paused True), emit exactly one on_alert, and keep pending tickets
    (stats['failed'] == 0) — cancel then releases the run."""
    # Use a control you can cancel from a timer task once paused is observed.
```

Implement both concretely against the existing fixtures in that file (they already fake `browser_factory`, `page_portal_factory`, `login_once`).

- [ ] **Step 8: Run engine tests + full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_ticket_engine_async.py tests\test_supervisor.py -q` then `-m pytest tests\ -q`

```bash
git add scraper/supervisor.py scraper/ticket_engine.py scraper/ticket_engine_async.py tests/
git commit -m "feat(v4.0.3): BrowserSupervisor auto-recovery — no mass-fail on browser death (bug-116)"
```

---

### Task 6: Comment-count logging, download retries, NOT-FOUND fast path

**Files:**
- Modify: `scraper/ticket_engine_async.py` ([OK] log line)
- Modify: `scraper/portal/tradedesk_portal_async.py` (open_ticket fast path + download retry)
- Modify: `scraper/portal/contoso_portal.py` (download retry)
- Test: `tests/test_ticket_engine_async.py`, `tests/test_contoso_portal.py` (append)

**Interfaces:**
- Produces: `[OK]` log format both portals: `{prefix}[OK] #{tid}: {title} — {C} comment(s)/email(s), {F} file(s)` where C = `len(res.get("comments") or [])`, F = total files saved this ticket.
- Produces: `_retry_download(fn, attempts=2, base_delay=0.5)` helper local to each portal module (async, returns fn() result or raises last error).

- [ ] **Step 1: Write failing test for the log line (append to tests/test_ticket_engine_async.py)**

```python
def test_ok_log_line_includes_comment_and_file_counts():
    """R1: per-ticket [OK] line reports the main-thread comment count like the
    resolution line does. Drive one ticket through the engine with a parse_fn
    returning 3 comments and assert the captured log contains
    '3 comment(s)/email(s)'."""
```

Implement concretely with the file's existing fixtures (fake portal returning a data dict with `"comments": [{}, {}, {}]`).

- [ ] **Step 2: Change the engine's [OK] line**

In the worker success branch of `scraper/ticket_engine_async.py`, replace:

```python
                        cb.on_log("info", f"{prefix}[OK] #{tid}: {res.get('title') or ''}")
```

with:

```python
                        n_comments = len(res.get("comments") or [])
                        n_files = len(res.get("attachments") or [])
                        cb.on_log("info",
                            f"{prefix}[OK] #{tid}: {res.get('title') or ''} — "
                            f"{n_comments} comment(s)/email(s), {n_files} file(s)")
```

- [ ] **Step 3: tradedesk NOT-FOUND fast path + faster ready wait**

Replace `AsyncTradeDeskPortal.open_ticket` in `scraper/portal/tradedesk_portal_async.py`:

```python
    async def open_ticket(self, tid: str) -> str:
        """Fast-path readiness: poll every 250ms for EITHER the fields rendering
        (found) OR the SPA redirecting away (not-found -> /bugs). v4.0.2 burned a
        fixed 1.5s + up to 2×20s selector waits per ticket; 7,485 not-founds in
        one run paid full price (bug-117)."""
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        edit_path = f"/tickets/{tid}/edit"
        ready = False
        for _ in range(48):                     # ≤ ~12s in 250ms steps
            if edit_path not in self.page.url:
                return await self.page.content()          # redirected: not found
            try:
                if await self.page.locator("button.floating-dropdown-btn").count():
                    ready = True
                    break
            except Exception:
                pass
            await self.page.wait_for_timeout(250)
        if ready:
            try:
                await self.page.wait_for_selector("button.sidebar-menu-btn", timeout=8_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(300)
        return await self.page.content()
```

- [ ] **Step 4: Download retries (both portals)**

Add to `scraper/portal/tradedesk_portal_async.py` (module level, under `_unique_path`):

```python
async def _retry_download(fn, attempts: int = 2, base_delay: float = 0.5):
    """Run an async download op with small-backoff retries (bug-117: 213 one-shot
    download timeouts in a single v4.0.2 run). Raises the last error."""
    import asyncio
    last = None
    for i in range(attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last = exc
            if i < attempts:
                await asyncio.sleep(base_delay * (2 ** i))
    raise last
```

In `AsyncTradeDeskPortal.download_all`, wrap the per-button body:

```python
        for i, btn in enumerate(btns):
            async def _one(btn=btn):
                async with self.page.expect_download(timeout=30_000) as dl:
                    await btn.click()
                d = await dl.value
                target = _unique_path(dest_dir, d.suggested_filename)
                await d.save_as(str(target))
                return target
            try:
                saved.append(await _retry_download(_one))
            except Exception as exc:
                skipped += 1
                log.warning("download_all: button %d/%d failed after retries (%s)",
                            i + 1, len(btns), type(exc).__name__)
```

Copy the same `_retry_download` helper into `scraper/portal/contoso_portal.py` and wrap its per-URL body:

```python
        for i, (url, label) in enumerate(urls):
            async def _one(url=url, label=label, i=i):
                resp = await self.page.context.request.get(url)
                if not resp.ok:
                    raise RuntimeError(f"http_{resp.status}")
                body = await resp.body()
                target = _unique_path(dest_dir, _filename_for(resp, label, i))
                target.write_bytes(body)
                return target
            try:
                saved.append(await _retry_download(_one))
            except Exception as exc:
                log.warning("download_all: attachment %d/%d failed after retries (%s)",
                            i + 1, len(urls), type(exc).__name__)
```

- [ ] **Step 5: Append a retry test to `tests/test_contoso_portal.py`**

```python
def test_download_all_retries_transient_failures(tmp_path):
    """First GET raises, retry succeeds -> file saved, nothing skipped."""
    # Build the portal with the file's existing fake page/context pattern; make
    # context.request.get fail once (TimeoutError) then return a 200 response
    # with body b"data". Assert len(saved) == 1.
```

Implement concretely against the fixtures already in that file.

- [ ] **Step 6: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_ticket_engine_async.py tests\test_contoso_portal.py tests\test_tradedesk_portal.py -q` then full suite.

```bash
git add scraper/ticket_engine_async.py scraper/portal/ tests/
git commit -m "feat(v4.0.3): comment-count in [OK] log, download retries, not-found fast path (bug-117)"
```

---

### Task 7: Live worker target + resource tuner task in the engine

**Files:**
- Modify: `scraper/control.py` (target_workers)
- Modify: `scraper/ticket_engine_async.py` (park/unpark + tuner task)
- Test: `tests/test_run_control.py`, `tests/test_ticket_engine_async.py` (append)

**Interfaces:**
- Consumes: `AdaptiveGate.tune`/`set_ceiling` (Task 3), `ResourceSampler` (Task 1).
- Produces: `RunControl.target_workers: int | None` (None = no override; set from the GUI thread — a single int assignment, safe under the GIL). Engine: `run_ticket_scrape_async(..., sampler=None)` new keyword; workers with `idx >= effective_target` park (close their page, poll 0.5s); a `_tuner` task every 2s does `gate.tune(snap.cpu_pct, snap.ram_free_mb)` + `gate.set_ceiling(effective_target)`.

- [ ] **Step 1: Failing tests**

Append to `tests/test_run_control.py`:

```python
def test_target_workers_defaults_none_and_is_settable():
    c = RunControl()
    assert c.target_workers is None
    c.target_workers = 3
    assert c.target_workers == 3
```

Append to `tests/test_ticket_engine_async.py`:

```python
def test_workers_park_when_target_lowered():
    """Start 4 workers over a slow queue; set control.target_workers = 1 after the
    first ticket; assert the run still completes ALL tickets (parked workers hold
    no pages) and that at the end only ≤1 worker was actively pulling: track
    concurrent in-flight via the fake portal and assert its max after the change
    is 1."""

def test_tuner_calls_gate_tune_with_sampler_values():
    """Pass a fake sampler yielding cpu=99 -> engine's gate.permits must drop
    below max within the run (observe via a probe fake portal that reads the
    gate). Keep the batch small so the test is fast."""
```

Implement concretely with the file's fixtures.

- [ ] **Step 2: `RunControl.target_workers`**

In `scraper/control.py` `__init__` add: `self.target_workers: int | None = None`.

- [ ] **Step 3: Engine changes**

In `run_ticket_scrape_async`:
- Signature: add keyword `sampler=None` (docstring: "ResourceSampler or None; None disables resource tuning — tests and callers without psutil").
- In the worker loop, right after `await control.wait_if_paused_async()` / cancel check, add parking:

```python
                target = control.target_workers or workers
                if idx >= max(1, min(workers, target)):
                    # Parked (live worker-slider lowered): hold no page, keep polling.
                    if page is not None:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        page = None
                    await asyncio.sleep(0.5)
                    continue
                if page is None:   # un-parked (or first loop after park): reacquire
                    try:
                        own_browser, page = await _open_worker_page()
                        portal = page_portal_factory(page)
                    except Exception:
                        await asyncio.sleep(1.0)
                        continue
```

  Note: the worker's initial `_open_worker_page()` before the loop moves INTO the loop via this `if page is None` block — delete the pre-loop `try: own_browser, page = await _open_worker_page() ... return` block and let the first iteration acquire the page (startup failures now retry instead of killing the worker; cancel still exits).
- Tuner task (add just before `await asyncio.gather(...)`, gathering it too and cancelling when workers finish):

```python
        async def _tuner():
            while True:
                await asyncio.sleep(2.0)
                if control.cancelled:
                    return
                target = control.target_workers or workers
                gate.set_ceiling(max(1, min(workers, target)))
                if sampler is not None:
                    try:
                        snap = sampler.sample()
                        gate.tune(snap.cpu_pct, snap.ram_free_mb)
                    except Exception:
                        pass
```

```python
            n_workers = max(1, min(workers, total))
            gate = AdaptiveGate(n_workers)
            tuner = asyncio.ensure_future(_tuner())
            try:
                await asyncio.gather(*(worker(i, gate) for i in range(n_workers)))
            finally:
                tuner.cancel()
```

- In `scraper/async_runner.py`, construct the sampler for real runs:

```python
        sampler = None
        try:
            from scraper.resmon import ResourceSampler
            sampler = ResourceSampler()
        except Exception:
            sampler = None
```

and pass `sampler=sampler` to `run_ticket_scrape_async`.

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_run_control.py tests\test_ticket_engine_async.py tests\test_async_runner.py -q` then full suite.

```bash
git add scraper/control.py scraper/ticket_engine_async.py scraper/async_runner.py tests/
git commit -m "feat(v4.0.3): live worker target (park/unpark) + resource tuner task"
```

---

### Task 8: Alert popups + single-run guard (GUI wiring)

**Files:**
- Create: `scraper/run_registry.py`
- Modify: `scraper/async_runner.py` (alert Signal)
- Modify: `scraper/ticket_tab.py` (alert dialog, registry acquire/release)
- Modify: `scraper/kb_tab.py` (registry acquire/release on its start/finish handlers)
- Test: `tests/test_run_registry.py`, `tests/test_ticket_tab.py` (append)

**Interfaces:**
- Produces: `run_registry.acquire(owner: str) -> bool`, `run_registry.owner() -> str | None`, `run_registry.release(owner: str) -> None` (module-level, threading.Lock; release by non-owner is a no-op).
- Produces: `AsyncTicketWorker.alert = Signal(str, str, str)` wired from `cb.on_alert`.

- [ ] **Step 1: Failing registry tests**

```python
# tests/test_run_registry.py
"""Single-run guard: only one scrape across all tabs (R7)."""
import scraper.run_registry as rr


def setup_function(_):
    rr.release(rr.owner() or "")


def test_acquire_release_cycle():
    assert rr.owner() is None
    assert rr.acquire("Tickets — tradedesk") is True
    assert rr.owner() == "Tickets — tradedesk"
    assert rr.acquire("Tickets — Legacy") is False      # blocked
    rr.release("Tickets — tradedesk")
    assert rr.owner() is None
    assert rr.acquire("Tickets — Legacy") is True


def test_release_by_non_owner_is_noop():
    rr.acquire("A")
    rr.release("B")
    assert rr.owner() == "A"


def test_reacquire_by_same_owner_is_true():
    rr.acquire("A")
    assert rr.acquire("A") is True
```

- [ ] **Step 2: Implement `scraper/run_registry.py`**

```python
"""Single-run guard (v4.0.3, R7). One scrape at a time across ALL tabs — the
2026-07-02 collapse happened while tradedesk + Legacy batches overlapped in one
process. Module-level so every tab shares it."""
from __future__ import annotations
import threading

_lock = threading.Lock()
_owner: str | None = None


def acquire(owner: str) -> bool:
    global _owner
    with _lock:
        if _owner is None or _owner == owner:
            _owner = owner
            return True
        return False


def owner() -> str | None:
    return _owner


def release(owner: str) -> None:
    global _owner
    with _lock:
        if _owner == owner:
            _owner = None
```

- [ ] **Step 3: Alert signal in `scraper/async_runner.py`**

Add `alert = Signal(str, str, str)` to the class signals, and in `run()`'s callbacks add `on_alert=lambda sev, title, body: self.alert.emit(sev, title, body),`.

- [ ] **Step 4: Wire ticket_tab — registry + alert dialog + release**

In `scraper/ticket_tab.py`:
- `import scraper.run_registry as run_registry` and give each tab a name: in `__init__`, `self._run_name = f"Tickets — {portal_kind}"`.
- At the very top of `_start()` (before credentials):

```python
        if not run_registry.acquire(self._run_name):
            QMessageBox.warning(
                self, "Another scrape is running",
                f"A scrape is already running on '{run_registry.owner()}'.\n"
                "Only one scrape can run at a time — wait for it to finish or stop it.")
            return
```

- Every early `return` in `_start()` after that point must `run_registry.release(self._run_name)` first (credentials missing, empty input, unparseable IDs).
- Connect the alert signal after the other worker connections: `self._worker.alert.connect(self._on_alert)`.
- Release in `_worker_thread_done` (runs for every outcome including engine crash):

```python
    @Slot()
    def _worker_thread_done(self):
        run_registry.release(self._run_name)
        self._set_running(False)
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)
```

- Alert handler (non-modal so the engine keeps running behind it; also un-pauses the Pause button label into Resume state when the engine paused itself):

```python
    @Slot(str, str, str)
    def _on_alert(self, severity: str, title: str, body: str):
        if self._control.paused:
            self.btn_pause.setText("▶ Resume")
        icon = QMessageBox.Critical if severity == "error" else QMessageBox.Warning
        box = QMessageBox(icon, title, body, QMessageBox.Ok, self)
        box.setWindowModality(Qt.NonModal)
        box.show()
        self._alert_box = box   # keep a ref so it isn't GC'd
```

  Add `from PySide6.QtCore import Qt, Slot` to the imports (Qt is new here).
- Resume must clear a supervisor give-up: nothing to do in the tab — the engine's recovery loop calls `supervisor.reset_give_up()` itself after `wait_if_paused_async` returns (Task 5).

- [ ] **Step 5: KB tab registry**

In `scraper/kb_tab.py`, mirror the same acquire/release: `import scraper.run_registry as run_registry`; acquire with name `"Knowledge Base"` at the top of every start handler that calls `self.worker.start()` (grep the five `.start()` sites — one acquire in the common start helper if one exists, else in each), show the same warning QMessageBox on refusal, and release in its finished/thread-done handler.

- [ ] **Step 6: GUI tests (append to `tests/test_ticket_tab.py`)**

```python
def test_start_blocked_while_registry_busy(qtbot_or_existing_fixture):
    """Acquire the registry as 'other', call tab._start() with valid-looking
    input, assert no worker was created and the registry owner is unchanged.
    (Monkeypatch QMessageBox.warning to a recorder — follow this file's
    existing dialog-stub pattern.)"""

def test_alert_slot_shows_nonmodal_box():
    """Call tab._on_alert('error', 'T', 'B') and assert tab._alert_box exists
    with windowTitle 'T'."""

def test_worker_done_releases_registry():
    """Acquire as the tab's own run name, call tab._worker_thread_done(),
    assert run_registry.owner() is None."""
```

Implement concretely following the file's existing offscreen-Qt fixtures.

- [ ] **Step 7: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_run_registry.py tests\test_ticket_tab.py tests\test_kb_tab.py tests\test_async_runner.py -q` then full suite.

```bash
git add scraper/run_registry.py scraper/async_runner.py scraper/ticket_tab.py scraper/kb_tab.py tests/
git commit -m "feat(v4.0.3): alert popups + single-run guard across tabs"
```

---

### Task 9: GUI freeze fixes — log buffering + lazy table rows

**Files:**
- Modify: `scraper/ticket_tab.py`
- Test: `tests/test_ticket_tab.py` (append)

**Interfaces:**
- Produces: `TicketTab.BIG_BATCH_ROWS = 2000` — batches larger than this skip row pre-creation; rows are appended on first ticket event. `TicketTab._emit_log` becomes buffer-only; `TicketTab._flush_log()` drains on a 250ms QTimer.

- [ ] **Step 1: Failing tests (append to tests/test_ticket_tab.py)**

```python
def test_big_batch_skips_row_precreation():
    """Feed _start() 2001+ ticket ids (stub worker so nothing real runs — follow
    the file's existing worker-stub pattern): table.rowCount() == 0 and
    _ticket_rows is empty; then simulate _on_ticket_done('55555', 'ok') and
    assert one row appeared with the right status."""

def test_small_batch_still_precreates_rows():
    """With 5 ids, rowCount() == 5 (existing behavior preserved)."""

def test_log_lines_are_buffered_then_flushed():
    """Call tab._emit_log('info', 'x') 50 times: log_pane blockCount() must not
    grow yet (≤1); after tab._flush_log(), the pane contains 50 lines and the
    buffer is empty."""
```

- [ ] **Step 2: Implement log buffering**

In `TicketTab.__init__`: add

```python
        self._log_buf: list[tuple[str, str, str]] = []   # (ts, level, msg)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(250)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start()
```

(`from PySide6.QtCore import QTimer` — extend the QtCore import.)

Replace `_emit_log` and add `_flush_log`:

```python
    _LOG_COLORS = {"error": "#c62828", "warning": "#ef6c00", "info": "#212121"}

    @Slot(str, str)
    def _emit_log(self, level: str, msg: str):
        """Buffer only — a 30k-ticket run at 10 workers emits log lines faster
        than QPlainTextEdit can append+scroll one-by-one (bug-115 UI freeze).
        A 250ms timer flushes the buffer as ONE insert."""
        self._log_buf.append((datetime.now().strftime("%H:%M:%S"), level, msg))
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(msg)

    def _flush_log(self):
        if not self._log_buf:
            return
        buf, self._log_buf = self._log_buf, []
        import html as _html
        parts = []
        for ts_str, level, msg in buf:
            color = self._LOG_COLORS.get(level, "#616161")
            parts.append(f'<span style="color:{color}">'
                         f'{ts_str} {level.upper():7s} {_html.escape(msg)}</span>')
        self.log_pane.appendHtml("<br>".join(parts))
        self.log_pane.verticalScrollBar().setValue(
            self.log_pane.verticalScrollBar().maximum())
```

(`setMaximumBlockCount(MAX_LOG_LINES)` already trims old lines.)

- [ ] **Step 3: Implement lazy table rows**

Add class constant `BIG_BATCH_ROWS = 2000`. In `_start()`, replace the row pre-creation loop:

```python
        self.table.setRowCount(0)
        self._ticket_rows.clear()
        self._big_batch = len(ticket_ids) > self.BIG_BATCH_ROWS
        if self._big_batch:
            # Pre-creating 30k QTableWidget rows froze the UI (bug-115); rows are
            # appended as tickets complete instead.
            self._emit_log("info",
                f"Large batch ({len(ticket_ids)} tickets): results table fills as "
                "tickets complete.")
        else:
            for tid in ticket_ids:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(f"#{tid}"))
                item_status = QTableWidgetItem("Queued")
                item_status.setForeground(QColor("#616161"))
                self.table.setItem(row, 1, item_status)
                self.table.setItem(row, 2, QTableWidgetItem(""))
                self.table.setItem(row, 3, QTableWidgetItem(""))
                self._ticket_rows[tid] = row
```

Add a lazy-row helper and use it in both ticket slots:

```python
    def _row_for(self, tid: str) -> int:
        row = self._ticket_rows.get(tid)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"#{tid}"))
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.table.setItem(row, 3, QTableWidgetItem(""))
            self._ticket_rows[tid] = row
        return row
```

In `_on_ticket_done` and `_on_ticket_meta`, replace the `row = self._ticket_rows.get(tid); if row is None: return` preamble with `row = self._row_for(tid)`.

Also in `__init__` set `self._big_batch = False`.

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_ticket_tab.py -q` then full suite.

```bash
git add scraper/ticket_tab.py tests/test_ticket_tab.py
git commit -m "fix(v4.0.3): GUI freeze — buffered log flush + lazy table rows for big batches (bug-115)"
```

---

### Task 10: Resource monitor panel + live controls UI

**Files:**
- Create: `scraper/resource_monitor.py`
- Modify: `scraper/ticket_tab.py` (mount panel; priority combo; live workers)
- Test: `tests/test_resource_monitor.py`, `tests/test_ticket_tab.py` (append)

**Interfaces:**
- Consumes: `ResourceSampler` (Task 1), `procctl.apply_priority` + `app_settings.priority`/`set_priority` (Task 2), `RunControl.target_workers` (Task 7).
- Produces: `ResourceMonitorWidget(sampler=None, parent=None)` (QGroupBox "Resources & Speed") with `.set_progress(current: int, total: int)` (feeds pace/ETA), `.set_workers_info(active: int)`, `.start()/.stop()` (QTimer 2s), `.refresh_now()` (test hook — one sample+render).

- [ ] **Step 1: Failing tests**

```python
# tests/test_resource_monitor.py
"""ResourceMonitorWidget — renders sampler data + pace/ETA. Offscreen Qt."""
# Follow the offscreen-Qt setup used by tests/test_ticket_tab.py (QApplication
# fixture / QT_QPA_PLATFORM=offscreen).
from scraper.resmon import ResourceSnapshot
from scraper.resource_monitor import ResourceMonitorWidget


class _FakeSampler:
    def sample(self):
        return ResourceSnapshot(cpu_pct=55.0, ram_total_mb=16000, ram_used_mb=9000,
                                ram_free_mb=7000, app_rss_mb=250,
                                chrome_procs=[(11, 400), (12, 300)], chrome_total_mb=700)


def test_refresh_renders_sampler_values(qapp):
    w = ResourceMonitorWidget(sampler=_FakeSampler())
    w.refresh_now()
    txt = w.lbl_system.text() + w.lbl_chrome.text()
    assert "55" in txt and "7000" in txt.replace(",", "") or "7,000" in txt
    assert "2 proc" in w.lbl_chrome.text()


def test_pace_and_eta_from_progress(qapp):
    w = ResourceMonitorWidget(sampler=_FakeSampler())
    w._clock = iter([0.0, 60.0]).__next__          # two ticks, 60s apart
    w.set_progress(0, 1000)
    w.set_progress(60, 1000)                        # 60 tickets/min
    assert "60" in w.lbl_pace.text()                # pace shown
    assert "15m" in w.lbl_pace.text() or "0h 15m" in w.lbl_pace.text()   # 940/60 ≈ 15.7m


def test_no_sampler_renders_dashes(qapp):
    w = ResourceMonitorWidget(sampler=None)
    w.refresh_now()
    assert "—" in w.lbl_system.text()
```

(Use/extend the existing `qapp` fixture pattern from tests/test_ticket_tab.py; if it's named differently there, match it.)

- [ ] **Step 2: Implement `scraper/resource_monitor.py`**

```python
"""Resource monitor panel (v4.0.3, R5): system CPU/RAM, app RAM, Chrome process
rollup, pace + ETA. Pure display — sampling comes from resmon.ResourceSampler;
pace comes from on_progress events. QTimer keeps refresh on the GUI thread."""
from __future__ import annotations
import time
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel


def _fmt_eta(minutes: float) -> str:
    if minutes <= 0 or minutes != minutes:      # NaN guard
        return "—"
    h, m = divmod(int(minutes + 0.5), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


class ResourceMonitorWidget(QGroupBox):
    def __init__(self, sampler=None, parent=None):
        super().__init__("Resources & Speed", parent)
        self._sampler = sampler
        self._clock = time.monotonic
        self._points: deque[tuple[float, int]] = deque(maxlen=90)   # (t, done) ~3min
        self._total = 0
        g = QGridLayout(self)
        g.setContentsMargins(10, 6, 10, 6)
        self.lbl_system = QLabel("CPU — · RAM —")
        self.lbl_app = QLabel("App —")
        self.lbl_chrome = QLabel("Chrome —")
        self.lbl_workers = QLabel("Workers —")
        self.lbl_pace = QLabel("Pace — · ETA —")
        for i, w in enumerate((self.lbl_system, self.lbl_app, self.lbl_chrome,
                               self.lbl_workers, self.lbl_pace)):
            g.addWidget(w, i // 3, i % 3)
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh_now)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_workers_info(self, active: int):
        self.lbl_workers.setText(f"Workers {active}")

    def set_progress(self, current: int, total: int):
        self._total = total
        self._points.append((self._clock(), current))
        if len(self._points) >= 2:
            (t0, c0), (t1, c1) = self._points[0], self._points[-1]
            if t1 > t0 and c1 > c0:
                per_min = (c1 - c0) / (t1 - t0) * 60.0
                remaining = max(0, total - c1)
                self.lbl_pace.setText(
                    f"Pace {per_min:.0f}/min · ETA {_fmt_eta(remaining / per_min)}")

    def reset_run(self):
        self._points.clear()
        self.lbl_pace.setText("Pace — · ETA —")

    def refresh_now(self):
        if self._sampler is None:
            self.lbl_system.setText("CPU — · RAM —")
            return
        try:
            s = self._sampler.sample()
        except Exception:
            return
        self.lbl_system.setText(
            f"CPU {s.cpu_pct:.0f}% · RAM {s.ram_used_mb:,}/{s.ram_total_mb:,} MB "
            f"(free {s.ram_free_mb:,})")
        self.lbl_app.setText(f"App {s.app_rss_mb:,} MB")
        self.lbl_chrome.setText(
            f"Chrome {len(s.chrome_procs)} proc · {s.chrome_total_mb:,} MB")
        self.lbl_chrome.setToolTip("\n".join(
            f"PID {pid}: {mb:,} MB" for pid, mb in s.chrome_procs) or "no Chrome processes")
```

- [ ] **Step 3: Mount in `ticket_tab.py` + priority combo + live workers**

In `_build_ui`, after the progress row: create the sampler once (guarded) and the panel:

```python
        try:
            from scraper.resmon import ResourceSampler
            self._sampler = ResourceSampler()
        except Exception:
            self._sampler = None
        from scraper.resource_monitor import ResourceMonitorWidget
        self.monitor = ResourceMonitorWidget(sampler=self._sampler)
        outer.addWidget(self.monitor)
        self.monitor.start()
```

In `_build_workers_row`, after the spinbox hint label, add the priority control:

```python
        row.addSpacing(24)
        lbl_p = QLabel("Priority:")
        lbl_p.setStyleSheet("font-weight: bold;")
        self.cmb_priority = QComboBox()
        self.cmb_priority.addItems(["Low", "Normal", "High"])
        self.cmb_priority.setCurrentText(app_settings.priority().title())
        self.cmb_priority.setToolTip(
            "Windows process priority for the scraper and its Chrome processes.\n"
            "High = faster on a busy machine (no more Task Manager).")
        self.cmb_priority.currentTextChanged.connect(self._on_priority_changed)
        row.addWidget(lbl_p)
        row.addWidget(self.cmb_priority)
```

(`QComboBox` added to the QtWidgets import.) Handlers + reapply timer (Chrome respawns processes) in the class:

```python
    def _on_priority_changed(self, text: str):
        level = text.strip().lower()
        app_settings.set_priority(level)
        from scraper import procctl
        n = procctl.apply_priority(level)
        self._emit_log("info", f"Process priority set to {text} ({n} process(es)).")
```

In `__init__` add:

```python
        self._prio_timer = QTimer(self)
        self._prio_timer.setInterval(5000)
        self._prio_timer.timeout.connect(self._reapply_priority)
```

```python
    def _reapply_priority(self):
        from scraper import procctl
        procctl.apply_priority(app_settings.priority())
```

Start/stop it in `_set_running` (`self._prio_timer.start() if running else self._prio_timer.stop()`), and apply once at run start (`self._on_priority_changed(self.cmb_priority.currentText())` right after `self._worker.start()` — Chrome children appear a moment later; the 5s reapply covers them).

Live workers: in `_set_running`, REMOVE `self.spn_workers.setEnabled(not running)` (spinbox stays enabled). In `_start()` connect once per run after creating the control: `self._control.target_workers = None`, and add in `__init__`: `self.spn_workers.valueChanged.connect(self._on_workers_changed)` with:

```python
    def _on_workers_changed(self, value: int):
        if self._worker is not None and self._worker.isRunning():
            self._control.target_workers = value
            self.monitor.set_workers_info(value)
            self._emit_log("info", f"Workers target changed to {value} (live).")
```

Feed the monitor: in `_on_progress` add `self.monitor.set_progress(current, total)`; in `_start()` add `self.monitor.reset_run()` and `self.monitor.set_workers_info(workers)`.

- [ ] **Step 4: Append a ticket_tab test**

```python
def test_live_worker_change_updates_control_target():
    """With a stubbed running worker (isRunning() True), set spn_workers to 2 and
    assert tab._control.target_workers == 2. Follow the file's worker-stub
    pattern."""
```

- [ ] **Step 5: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_resource_monitor.py tests\test_ticket_tab.py -q` then full suite.

```bash
git add scraper/resource_monitor.py scraper/ticket_tab.py tests/
git commit -m "feat(v4.0.3): resource monitor panel + priority control + live worker slider"
```

---

### Task 11: Version 4.0.3 + build assets + docs

**Files:**
- Modify: `scraper/config.py` (APP_VERSION), `tests/test_version.py` (or the scraper version test — locate with `grep -rn "4.0.2" tests/`)
- Create: `ContosoKBScraper-v4.0.3.spec` (copy of `ContosoKBScraper-v4.0.2.spec` with name/paths updated; ADD `psutil` to hiddenimports if the 4.0.2 spec lists hiddenimports explicitly — check)
- Create: `build_scraper_exe_v403.bat`
- Modify: `library/tradedesk/CHANGELOG.md`? No — the scraper changelog: locate with `grep -rn "4.0.2" --include=CHANGELOG.md .` and update the same file v4.0.2 used (repo-root or scraper CHANGELOG; follow the v4.0.2 commit `4cca16c` pattern via `git show 4cca16c --stat`)
- Modify: `.wolf/buglog.json`, `.wolf/cerebrum.md`, `.wolf/memory.md`, `.wolf/anatomy.md`

**Interfaces:**
- Produces: `APP_VERSION = "4.0.3"`; `build_scraper_exe_v403.bat` → `dist\ContosoKBScraper-v4.0.3\ContosoKBScraper.exe` with `--workpath build_v403`.

- [ ] **Step 1: Version bump + test**

`scraper/config.py`: `APP_VERSION = "4.0.3"`. Update the version test found by `grep -rn "4\.0\.2" tests/` to expect `4.0.3`.

- [ ] **Step 2: Spec + bat**

Copy `ContosoKBScraper-v4.0.2.spec` → `ContosoKBScraper-v4.0.3.spec`; replace every `4.0.2` with `4.0.3` inside. Create `build_scraper_exe_v403.bat`:

```bat
@echo off
REM One-folder v4.0.3 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.3.spec --noconfirm --workpath build_v403 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.3\ContosoKBScraper.exe
```

- [ ] **Step 3: Bug log entries (`.wolf/buglog.json`)**

Append (matching the existing JSON structure — read the last entry first for the exact shape):
- `bug-115`: UI freeze on big batches — root cause: per-line log appends + pre-creating 19k QTableWidget rows with ResizeToContents columns; fix: 250ms buffered log flush + lazy rows > 2000.
- `bug-116`: 28,620 tickets mass-failed 2026-07-02 10:57 — root cause: shared Chrome died (socket.send bursts), light mode had no browser-level recovery so all workers exited and drain_to_failed fired; breaker skipped on worker-exit path; fix: BrowserSupervisor single-flight restart+relogin, pause+alert instead of drain, breaker+alert on all paths.
- `bug-117`: speed waste — one-shot download failures (213/run), fixed 1.5s+2×20s waits on 7,485 not-found tickets, full state-file rewrite per save; fix: download retries, 250ms-poll fast path, journaled batched state.
- `bug-118`: no operator-visible explanation when a run stops (breaker pause was log-only); fix: on_alert popups with WHAT/WHY/PRESERVED/DO.

- [ ] **Step 4: Cerebrum + memory + anatomy**

`.wolf/cerebrum.md`: add Do-Not-Repeat entries — (a) never drain-to-failed on infra failure (pause+alert; drain only for cancel/startup-login-failure); (b) QPlainTextEdit per-line appends + QTableWidget row pre-creation with ResizeToContents kill the GUI on 10k+ item runs — buffer + lazy rows; (c) light-mode shared browser needs SUPERVISED recovery — a tab-level rebuild loop can't survive browser death. Key Learnings: psutil priority classes mapping + "chrome children get ABOVE_NORMAL not HIGH". Update `.wolf/anatomy.md` with the new files (resmon, procctl, scrape_state, supervisor, run_registry, resource_monitor, spec/bat). Append a `.wolf/memory.md` line.

- [ ] **Step 5: Changelog**

Follow the file+format v4.0.2 used (`git show 4cca16c --stat` shows which changelog file it touched). Entry: v4.0.3 — auto-recovery (no mass-fail), explanatory popup alerts, resource auto-tune + monitor panel, live priority/worker controls, single-run guard, comment-count logging, download retries, not-found fast path, batched state writes, big-batch UI freeze fixes.

- [ ] **Step 6: Full suite + commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\ -q`
Expected: ≥ 290 passed

```bash
git add -A
git commit -m "chore(v4.0.3): version bump, build spec/bat, changelog, buglog + cerebrum learnings"
```

---

### Task 12: Live validation + package (GATED — operator confirmation before build)

**Files:**
- Create: none permanent (validation script goes to the session scratchpad)
- Modify: none (build outputs to `dist/ContosoKBScraper-v4.0.3/`)

**Interfaces:**
- Consumes: everything above; keyring credentials (same entry both portals).

- [ ] **Step 1: Source-mode live smoke (small)**

Run the GUI from source (`scraper\venv\Scripts\python.exe scraper\gui.py`) OR drive the engine headless via a scratchpad script (pattern: scratchpad `val_headless_scale.py` from v4.0.2). Validate, on ~100 tradedesk tickets @ 8 workers headless AND ~100 legacy tickets @ 8:
- comment counts appear in `[OK]` lines;
- pace ≥ v4.0.2 baseline (tradedesk > 19/min);
- monitor panel updates; priority High visibly changes Chrome priorities (check via `psutil` snippet or Task Manager);
- live worker slider mid-run: log line + Chrome tab count follows.

- [ ] **Step 2: Kill-Chrome recovery demo**

Mid-run (source mode), kill the Chrome process tree (`taskkill /IM chrome.exe /F` scoped to the test — or kill the specific PIDs from the monitor tooltip). MUST observe: "shared browser recovery" log, run continues, `failed` does NOT jump by the remaining count. Then simulate give-up (disconnect network or kill repeatedly) → popup appears, run pauses, Resume retries.

- [ ] **Step 3: STOP — operator confirmation**

Report smoke results to the user and get explicit approval BEFORE building the exe (standing rule).

- [ ] **Step 4: Build + frozen boot check**

```
build_scraper_exe_v403.bat
```

Boot `dist\ContosoKBScraper-v4.0.3\ContosoKBScraper.exe`: window shows v4.0.3, three tabs, monitor panel live, Settings opens. Run a 5-ticket scrape from the exe.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(v4.0.3): validated live — auto-recovery, speed, monitor; packaged dist/ContosoKBScraper-v4.0.3"
```

---

## Self-Review Notes

- Spec §3.1–3.8 → Tasks 5, 2/10, 3/7, 4/6, 10, 7, 8, 9, 6; §5 testing woven per-task; §6 ship = Tasks 11–12. Multi-window "last worker" softening (§3.1) is covered by Task 5's multi-mode bounded path + Task 5 Step 6.7 leftover-alert (drain now alerts loudly instead of silently).
- Type consistency: `on_alert(sev, title, body)` used identically in engine, supervisor, runner Signal, and tab slot. `ScrapedState.mark/flush/load` names consistent. `AdaptiveGate.tune/set_ceiling` consistent between Tasks 3 and 7.
- Tests that reference existing fixtures (Tasks 5/6/7/8/10) direct the implementer to read the fixture patterns first — the test INTENT and assertions are fully specified.
