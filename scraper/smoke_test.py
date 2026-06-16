"""Ticket Portal smoke test — runs the FULL login+extract+resolution pipeline.

Prints all extracted fields. Only the workers test (Step 4) saves to disk.
Password is read via getpass (never echoed, never logged, never stored).

Usage (from project root):
    scraper\\venv\\Scripts\\python.exe scraper\\smoke_test.py [ticket_id [ticket_id2]]

Example (single ticket):
    scraper\\venv\\Scripts\\python.exe scraper\\smoke_test.py 76500
Example (workers=2 test with two tickets):
    scraper\\venv\\Scripts\\python.exe scraper\\smoke_test.py 76500 76108
"""
import sys
import getpass
import json

# ── Bootstrap path so imports work from project root ─────────────────────────
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.core import Browser, _is_browser_dead
from scraper.parsers.ticket_parser import is_not_found, parse_ticket_detail, parse_resolution
from scraper.ticket_engine import run_ticket_scrape, TicketEngineCallbacks, TICKETS_DIR

BOGUS_ID = "99999999"   # should always be "not found"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_logged_out(html: str) -> bool:
    """True when the login page is being shown.

    Confirmed 2026-06-09: login page has id="user" and id="pw".
    Neither appear on any authenticated page.
    """
    h = html.lower()
    return 'id="user"' in h and 'id="pw"' in h


def _login(browser: Browser, base: str, username: str, password: str) -> bool:
    print(f"  → Navigating to portal: {base}")
    browser.navigate(base)
    html = browser.get_content()

    if not _is_logged_out(html):
        print("  → Session already active (no login needed).")
        return True

    print("  → Login page detected. Filling credentials...")
    browser.fill("#user", username)
    browser.fill("#pw", password)
    browser.click("input[name='ctl01']")
    browser.wait_for_load(timeout_ms=15_000)

    html = browser.get_content()
    if _is_logged_out(html):
        print("  [FAIL] Still on login page after submit — wrong credentials?")
        return False

    print("  → Login successful.")
    return True


def _fetch_and_print(browser: Browser, base: str, ticket_id: str) -> bool:
    """Returns True if a real ticket was fetched and parsed, False otherwise."""
    detail_url     = f"{base}/edit_bug.aspx?id={ticket_id}"
    resolution_url = f"{base}/Resolution.aspx?bugid={ticket_id}"

    print(f"\n  → Fetching ticket #{ticket_id}: {detail_url}")
    browser.navigate(detail_url)
    html = browser.get_content()

    if _is_logged_out(html):
        print("  [FAIL] Got redirected to login page. Session expired.")
        return False

    if is_not_found(html, ticket_id):
        print(f"  → Ticket #{ticket_id} NOT FOUND on portal (expected for bogus ID).")
        return False

    data = parse_ticket_detail(html, ticket_id, base)
    if not data:
        print(f"  [FAIL] Parser returned empty dict for #{ticket_id}.")
        print("         This likely means the login succeeded but parsing failed.")
        print("         Check _LABEL_MAP in ticket_parser.py against live portal labels.")
        return False

    # Resolution
    print(f"  → Fetching resolution: {resolution_url}")
    browser.navigate(resolution_url)
    res_html = browser.get_content()
    resolution = parse_resolution(res_html)
    if resolution:
        data["resolution"] = resolution

    # ── Print all fields ──────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"  TICKET #{ticket_id} — ALL EXTRACTED FIELDS")
    print(f"{'─' * 60}")

    FIELD_ORDER = [
        "ticket_id", "title", "product", "organization", "category",
        "priority", "severity", "status", "total_status", "scope_status",
        "module", "sprint", "tags", "assignee", "sqa_assignee", "csqa_owner",
        "created_by", "created_at",
        "site1_qa_signoff", "site2_qa_signoff",
        "dev_estimate_hrs", "qa_estimate_hrs",
        "dev_actual_hrs", "qa_actual_hrs", "csqa_actual_hrs", "other_actual_hrs",
        "estimate_start_date", "estimate_dev_end_date",
        "estimate_qa_start_date", "estimated_qa_completion_date",
        "estimated_client_delivery_date", "internal_target_date",
        "delay_count", "delay_days",
        "tfs_id", "release_ver", "is_parked", "awaiting_production_deployment",
        "environment_details", "scope_note", "ticket_type", "deployment",
        "resolution",
        "url", "resolution_url", "scraped_at",
    ]
    printed = set()
    for key in FIELD_ORDER:
        if key in data:
            val = data[key]
            if isinstance(val, list):
                continue   # handled below
            display = val if len(str(val)) <= 120 else str(val)[:117] + "..."
            print(f"  {key:<30} {display}")
            printed.add(key)

    # Any extra scalar fields not in FIELD_ORDER
    extras = {k: v for k, v in data.items()
              if k not in printed and k != "comments" and not isinstance(v, list)}
    if extras:
        print(f"\n  --- Additional fields ---")
        for k, v in extras.items():
            print(f"  {k:<30} {v}")

    # Comments
    comments = data.get("comments", [])
    if comments:
        print(f"\n  --- Comments & Emails ({len(comments)}) ---")
        for c in comments:
            ctype  = c.get("type", "?")
            author = c.get("author", "?")
            date   = c.get("date", "")
            cid    = c.get("id", "")
            body   = c.get("body", "")[:200]
            images = c.get("attachment_images") or []
            print(f"  [{ctype} #{cid}] {author} on {date}")
            print(f"    {body}")
            if images:
                mimes = ", ".join(img.get("mime", "?") for img in images)
                print(f"    [v3.1] {len(images)} inline image(s): {mimes}")
    else:
        print(f"\n  (no comments found)")

    field_count = len([v for v in data.values()
                       if (isinstance(v, list) and v) or (not isinstance(v, list) and v and str(v).strip())])
    print(f"\n  Total non-empty fields: {field_count}")
    print(f"{'─' * 60}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ticket_id  = sys.argv[1] if len(sys.argv) > 1 else "76500"
    ticket_id2 = sys.argv[2] if len(sys.argv) > 2 else None
    workers_ids = [ticket_id, ticket_id2] if ticket_id2 else [ticket_id]

    print("=" * 60)
    print("  TICKET PORTAL SMOKE TEST  (v3.1)")
    print("=" * 60)
    print(f"  Target ticket:  #{ticket_id}")
    if ticket_id2:
        print(f"  Second ticket:  #{ticket_id2}  (used for workers=2 test)")
    print(f"  Bogus ticket:   #{BOGUS_ID} (should be NOT FOUND)")
    print()

    portal_url = input("Portal URL [https://support.contoso.example]: ").strip()
    if not portal_url:
        portal_url = "https://support.contoso.example"

    username = input("Username: ").strip()
    password = getpass.getpass("Password (hidden): ")

    if not username or not password:
        print("[ABORT] Username and password are required.")
        sys.exit(1)

    print()
    base = portal_url.rstrip("/")

    browser = Browser(headless=False, timeout_ms=30_000)
    try:
        print("  → Launching headed Chrome...")
        browser.open()
    except Exception as exc:
        print(f"[FAIL] Could not launch browser: {exc}")
        sys.exit(1)

    overall_pass = True

    try:
        # ── Step 1: Login ─────────────────────────────────────────────────────
        print("\n[STEP 1] Login")
        if not _login(browser, base, username, password):
            print("\n[RESULT] FAIL — login did not succeed.")
            overall_pass = False
            return

        # ── Step 2: Real ticket ───────────────────────────────────────────────
        print(f"\n[STEP 2] Fetch real ticket #{ticket_id}")
        ok = _fetch_and_print(browser, base, ticket_id)
        if not ok:
            print(f"[FAIL] Ticket #{ticket_id} fetch/parse failed.")
            overall_pass = False

        # ── Step 3: Bogus ticket (should be not-found) ────────────────────────
        print(f"\n[STEP 3] Confirm bogus ticket #{BOGUS_ID} returns not-found")
        detail_url = f"{base}/edit_bug.aspx?id={BOGUS_ID}"
        browser.navigate(detail_url)
        html = browser.get_content()

        if _is_logged_out(html):
            print("  [FAIL] Session expired during not-found test.")
            overall_pass = False
        elif is_not_found(html, BOGUS_ID):
            print(f"  [PASS] Portal confirmed #{BOGUS_ID} does not exist.")
        else:
            print(f"  [WARN] Not-found detection unclear for #{BOGUS_ID}.")
            print("         Check is_not_found() in ticket_parser.py.")

        # ── Step 4: Workers=2 test (uses engine, SAVES to disk) ──────────────
        print(f"\n[STEP 4] workers=2 engine test on {workers_ids}")
        print(f"  NOTE: This step saves files to {TICKETS_DIR}")
        browser.close()   # release browser — engine opens its own

        step4_log = []
        def _log(lvl, msg):
            step4_log.append(f"  {lvl.upper():7s} {msg}")
            print(f"  {lvl.upper():7s} {msg}")

        engine_cb = TicketEngineCallbacks(
            on_log      = _log,
            on_progress = lambda i, n: print(f"  PROGRESS {i}/{n}"),
            on_ticket   = lambda tid, st: print(f"  TICKET   #{tid} → {st}"),
            on_finished = lambda rep: print(f"  DONE     {rep}"),
        )
        report = run_ticket_scrape(
            portal_url = base,
            username   = username,
            password   = password,
            ticket_ids = workers_ids,
            force      = True,
            cb         = engine_cb,
            workers    = min(2, len(workers_ids)),
        )
        if report.get("saved", 0) > 0 or report.get("skipped", 0) > 0:
            print(f"  [PASS] workers=2 engine test completed: {report}")
        else:
            print(f"  [WARN] workers=2 test — 0 saved/skipped. Review log above.")
            overall_pass = False

    except Exception as exc:
        print(f"\n[FAIL] Unexpected error: {exc}")
        import traceback
        traceback.print_exc()
        overall_pass = False
    finally:
        browser.close()

    print()
    print("=" * 60)
    if overall_pass:
        print("  SMOKE TEST: PASS")
    else:
        print("  SMOKE TEST: FAIL — review output above")
    print("=" * 60)


if __name__ == "__main__":
    main()
