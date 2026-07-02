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
