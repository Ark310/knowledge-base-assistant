"""Live end-to-end smoke test for the portal.contoso.example ticket scraper (v4).

Runs the FULL chain against the real portal: login -> open one ticket -> extract
fields/comments -> resolution -> download files -> write JSON+MD to a temp dir, then
prints a checklist of what was captured. This is the operator-confirmed gate before any
exe build (no exe is built until a human confirms a green smoke run).

Run from the Knowledge Base root (a real terminal — it prompts for your password):
    scraper\\venv\\Scripts\\python.exe scraper\\smoke_test.py --ticket 76511

Security: the password is read via getpass (never echoed), passed straight to the portal
login, and never written to disk or logged.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import tempfile
from pathlib import Path

# Allow running directly (`python scraper/smoke_test.py`): put the project root on the
# path so `import scraper.*` resolves (Python otherwise only adds scraper/ itself).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scraper.ticket_settings as ts
from scraper.ticket_engine import run_ticket_scrape, TicketEngineCallbacks


def main() -> None:
    saved = ts.load()
    ap = argparse.ArgumentParser(description="Live tradedesk ticket scrape smoke test.")
    ap.add_argument("--ticket", default="76511", help="ticket id to scrape end-to-end")
    ap.add_argument("--portal", default=saved.get("portal_url") or "https://portal.contoso.example")
    ap.add_argument("--username", default=saved.get("username") or "")
    args = ap.parse_args()

    username = args.username or input("Portal username: ").strip()
    password = ts.load_password(username) or getpass.getpass("Portal password (hidden): ")
    if not password:
        raise SystemExit("No password provided — aborting.")

    out_dir = Path(tempfile.mkdtemp(prefix="td_smoke_"))
    print(f"\nPortal : {args.portal}")
    print(f"User   : {username}")
    print(f"Ticket : #{args.ticket}")
    print(f"Output : {out_dir}\n{'-' * 60}")

    meta: dict = {}
    cb = TicketEngineCallbacks(
        on_log=lambda lvl, msg: print(f"  [{lvl}] {msg}"),
        on_progress=lambda i, n: None,
        on_ticket=lambda tid, st: print(f"  ticket #{tid}: {st}"),
        on_ticket_meta=lambda tid, title, nfiles: meta.update(title=title, files=nfiles),
        on_finished=lambda rep: meta.update(report=rep),
    )

    run_ticket_scrape(
        portal_url=args.portal, username=username, password=password,
        ticket_ids=[args.ticket], force=True, cb=cb, workers=1, output_dir=out_dir,
    )

    print("-" * 60)
    jpath = out_dir / f"ticket_{args.ticket}.json"
    if not jpath.exists():
        raise SystemExit(f"FAIL: no ticket JSON written (report={meta.get('report')}).")

    d = json.loads(jpath.read_text(encoding="utf-8"))
    comments = d.get("comments") or []
    res = d.get("resolution") or {}
    files = d.get("attachments") or []
    attach_dir = out_dir / "attachments" / args.ticket
    downloaded = sorted(attach_dir.glob("*")) if attach_dir.exists() else []

    def chk(ok: bool) -> str:
        return "OK " if ok else "-- "

    print("CHECKLIST:")
    print(f"  {chk(bool(d.get('product')))}product:        {d.get('product')}")
    print(f"  {chk(bool(d.get('organization')))}organization:   {d.get('organization')}")
    print(f"  {chk(bool(d.get('status')))}status:         {d.get('status')}")
    print(f"  {chk(bool(d.get('assignee')))}assignee:       {d.get('assignee')}")
    print(f"  {chk(bool(d.get('title')))}title:          {d.get('title')}")
    print(f"  {chk(len(comments) > 0)}comments:       {len(comments)}")
    print(f"  {chk(bool(res.get('text')))}resolution:     {len(res.get('text', ''))} chars, {len(res.get('attachments') or [])} file(s)")
    print(f"  {chk(len(files) > 0)}files (JSON):   {[a.get('filename') for a in files]}")
    print(f"  {chk(len(downloaded) > 0)}files on disk:  {[p.name for p in downloaded]}")
    print(f"\n  JSON: {jpath}\n  MD:   {out_dir / f'ticket_{args.ticket}.md'}")
    print("\nReview the files above. If fields/comments/resolution/files all look right,")
    print("the v4 ticket chain is confirmed against the live portal.")


if __name__ == "__main__":
    main()
