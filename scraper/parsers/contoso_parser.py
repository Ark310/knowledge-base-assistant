# scraper/parsers/contoso_parser.py
"""Parse ticket detail and resolution pages from support.contoso.example (legacy ASP.NET portal).

Ticket detail:  {portal}/edit_bug.aspx?id={ticket_id}
Resolution:     {portal}/Resolution.aspx?bugid={ticket_id}

Field labels confirmed from live portal JS inspection 2026-06-09.
Comments/emails confirmed from live DOM inspection 2026-06-09:
  - Each comment/email row has exactly 2 direct <table> children in cells[0]
  - table[0] = metadata header, table[1] = body text
  - Metadata-only rows (IMG + SPAN.pst) are skipped
Tags watermark: server HTML renders id="tags" input with value="tags" as a
  placeholder that JS clears on load — BeautifulSoup sees value="tags", so
  we skip inputs whose value equals their own id (watermark detection).
Created-by: "Created by X on DATE" text is in cells[0] (label), not cells[1].

Canonical schema (base_portal.empty_ticket):
  ticket_id, title, url, flat-fields, comments[{id,author,date,internal,body,
  images:[{mime,data}],attachments:[]}], resolution{text,comments[],attachments[]},
  attachments[]. Raw base64 is kept ONLY in comments[].images[].data here; the
  shared writer decodes and saves it — never store raw base64 elsewhere.
"""
from __future__ import annotations
import re

from bs4 import BeautifulSoup, NavigableString, Tag


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ── Label → field-name map ────────────────────────────────────────────────────
# Lowercase, colon-stripped label text → output key.
# More-specific entries MUST come before shorter substrings they contain.
# NOTE: "created by" is NOT here — it is extracted from the label text itself
#       via _extract_created_by() because the value cell holds UI widgets.
_LABEL_MAP: list[tuple[str, str]] = [
    # Title / description
    ("ticket id",                          "title"),
    # Environment details
    ("fx client server details",           "environment_details"),
    ("fxclientserverdetails",              "environment_details"),
    ("fx client server detail",            "environment_details"),
    ("environment",                        "environment_details"),
    # Status variants — more specific first
    ("total status",                       "total_status"),
    ("scope status",                       "scope_status"),
    ("status",                             "status"),
    # Assignee variants — more specific first
    ("sqa assign to",                      "sqa_assignee"),
    ("assigned to",                        "assignee"),
    ("assignee",                           "assignee"),
    ("csqa owner",                         "csqa_owner"),
    # QA signoffs
    ("site1 qa signoff",                     "site1_qa_signoff"),
    ("site2 qa signoff",                     "site2_qa_signoff"),
    # Hours — estimates before actuals (more specific)
    ("dev estimate hrs",                   "dev_estimate_hrs"),
    ("qa estimate hrs",                    "qa_estimate_hrs"),
    ("dev actual hrs",                     "dev_actual_hrs"),
    ("qa actual hrs",                      "qa_actual_hrs"),
    ("csqa actual hrs",                    "csqa_actual_hrs"),
    ("other actual hrs",                   "other_actual_hrs"),
    # Dates
    ("estimate start date",                "estimate_start_date"),
    ("estimate dev end date",              "estimate_dev_end_date"),
    ("estimate qa start date",             "estimate_qa_start_date"),
    ("estimated qa completion date",       "estimated_qa_completion_date"),
    ("estimated client delivery date",     "estimated_client_delivery_date"),
    ("internal target date",               "internal_target_date"),
    # Tracking
    ("tfs id",                             "tfs_id"),
    ("delay count",                        "delay_count"),
    ("delay days",                         "delay_days"),
    ("is this ticket parked",              "is_parked"),
    ("release ver",                        "release_ver"),
    ("awaiting_production_deployment",     "awaiting_production_deployment"),
    # Core fields confirmed from live portal
    ("project",                            "product"),
    ("organization",                       "organization"),
    ("organisation",                       "organization"),
    ("category",                           "category"),
    ("priority",                           "priority"),
    ("severity",                           "severity"),
    ("module",                             "module"),
    ("sprint",                             "sprint"),
    ("tags",                               "tags"),
    # Misc
    ("scope note",                         "scope_note"),
    ("type",                               "ticket_type"),
    ("deployment",                         "deployment"),
    # Fallback alternate label forms
    ("td client server",                  "product"),
]

# Values that mean "nothing selected" — skip them
_EMPTY_VALUES = {
    "", "-", "—", "n/a", "[not selected]", "-- select --",
    "none", "select...", "select one",
}

# Regex to parse the "Created by X on DATE" label text
_CREATED_BY_RE = re.compile(
    r"created\s+by\s+(\S+)\s+on\s+([\d-]+\s+[\d:]+\s+(?:AM|PM))",
    re.IGNORECASE,
)

# Regex to parse comment/email metadata header
_COMMENT_HDR_RE = re.compile(
    r"^comment\s+(\d+)\s+posted\s+by\s+(\S+)\s+on\s+([\d-]+\s+[\d:]+\s+(?:AM|PM))",
    re.IGNORECASE,
)
_EMAIL_HDR_RE = re.compile(
    r"^email\s+(\d+)\s+sent\s+to\s+(\S+)\s+by\s+(\S+)\s+on\s+([\d-]+\s+[\d:]+\s+(?:AM|PM))",
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def is_not_found(html: str, ticket_id: str) -> bool:
    """True when the portal says this ticket does not exist."""
    lower = html.lower()
    return (
        f"ticket not found: {ticket_id}" in lower
        or ("ticket not found" in lower and ticket_id in html)
    )


def parse_ticket_detail(html: str, ticket_id: str, portal_url: str) -> dict:
    """Extract all available fields from edit_bug.aspx.

    Returns a canonical-schema dict (ticket_id, title, url, flat fields,
    comments, resolution, attachments). Returns {} if not found or parse fails.
    """
    if is_not_found(html, ticket_id):
        return {}

    soup = BeautifulSoup(html, "lxml")
    fields: dict = {}

    # Walk every <tr>; treat first <td> as label, second as value
    for row in soup.find_all("tr"):
        cells = [c for c in row.find_all("td", recursive=False) if isinstance(c, Tag)]
        if len(cells) < 2:
            continue

        raw_label = _clean(cells[0].get_text()).rstrip(":").lower()
        raw_value = _get_cell_value(cells[1])

        if not raw_label or not raw_value or raw_value.lower() in _EMPTY_VALUES:
            continue

        for pattern, fname in _LABEL_MAP:
            if pattern in raw_label and fname not in fields:
                fields[fname] = raw_value
                break

    # Created-by — in label text, NOT in value cell
    _extract_created_by(soup, fields)

    # Comments and emails — structural extraction
    comments = _extract_comments(soup)

    base = portal_url.rstrip("/")
    return {
        "ticket_id":   ticket_id,
        "title":       fields.pop("title", ""),
        "url":         f"{base}/edit_bug.aspx?id={ticket_id}",
        **fields,
        "comments":    comments,
        "resolution":  {"text": "", "comments": [], "attachments": []},
        "attachments": [],
    }


def parse_resolution(html: str) -> dict:
    """Extract resolution from Resolution.aspx.

    Returns {"text": <str>, "comments": <list>, "attachments": <list>}.
    text is '' if absent, empty, or not found.  If the Resolution page carries
    a comment thread in the same markup as detail comments, it is captured here;
    otherwise comments=[].
    """
    if not html:
        return {"text": "", "comments": [], "attachments": []}

    soup = BeautifulSoup(html, "lxml")
    if "ticket not found" in soup.get_text().lower():
        return {"text": "", "comments": [], "attachments": []}

    # Primary: confirmed from portal HTML inspection
    text = ""
    area = soup.find("textarea", id="txtDescription")
    if area:
        text = _clean(area.get_text())
    else:
        # Fallback: any textarea inside resolutionForm
        form = soup.find("form", id="resolutionForm") or soup.find(
            "form", attrs={"name": "resolutionForm"}
        )
        if isinstance(form, Tag):
            area = form.find("textarea")
            if area:
                text = _clean(area.get_text())

    # If the Resolution page contains a comment thread (same row structure as
    # detail comments), capture it; otherwise comments=[].
    thread = _extract_comments(soup)

    return {"text": text, "comments": thread, "attachments": []}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cell_data_text(cell: Tag) -> str:
    """Text content of a cell with UI-chrome elements stripped.

    Excludes text that is a direct child of <a> or <button> tags — these are
    always navigation/action links (e.g. 'javascript:show_tags()' → 'tags',
    'javascript:show_calendar(...)' → '[select]'), never field data.
    """
    parts = []
    for node in cell.descendants:
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if isinstance(parent, Tag) and parent.name in ("a", "button", "script", "style"):
            continue
        parts.append(str(node))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _get_cell_value(cell: Tag) -> str:
    """Return the meaningful value from a table cell.

    Priority: <select> selected option → <input> value attr → text content.

    Watermark detection: skip <input> values that equal the input's own id
    (the portal renders value="tags" on the tags input as a placeholder; JS
    clears it at runtime but BeautifulSoup sees the server-rendered HTML).
    """
    # <select> dropdown — get the selected option's display text
    select = cell.find("select")
    if isinstance(select, Tag):
        selected_opt = select.find("option", selected=True)
        if selected_opt:
            t = _clean(selected_opt.get_text())
            if t and t.lower() not in _EMPTY_VALUES:
                return t
        for opt in select.find_all("option"):
            t = _clean(opt.get_text())
            if t and t.lower() not in _EMPTY_VALUES:
                return t

    # <input type="text|number"> — get value attribute
    for inp in cell.find_all("input"):
        itype = (inp.get("type") or "text").lower()
        if itype in ("text", "number", ""):
            val = _clean(inp.get("value", ""))
            # Skip watermark: value equals the input's own id or name
            inp_id   = (inp.get("id")   or "").lower()
            inp_name = (inp.get("name") or "").lower()
            if val.lower() in (inp_id, inp_name) and val:
                continue
            if val and val.lower() not in _EMPTY_VALUES:
                return val

    # Plain text — exclude UI control text (<a> and <button> descendants)
    # Tags cell: <a href="javascript:show_tags()">tags</a>  → must not leak
    # Date cells: <a href="javascript:show_calendar(...);">[select]</a> → must not leak
    return _clean(_cell_data_text(cell))


def _extract_created_by(soup: BeautifulSoup, fields: dict) -> None:
    """Find 'Created by X on DATE' in label cells and populate fields."""
    for row in soup.find_all("tr"):
        cells = [c for c in row.find_all("td", recursive=False) if isinstance(c, Tag)]
        if not cells:
            continue
        label_text = _clean(cells[0].get_text())
        m = _CREATED_BY_RE.search(label_text)
        if m:
            fields.setdefault("created_by", m.group(1))
            fields.setdefault("created_at", m.group(2).strip())
            return


def _extract_comments(soup: BeautifulSoup) -> list[dict]:
    """Extract all comments and email threads from the page.

    Structure (confirmed 2026-06-09 via live DOM inspection):
      Each comment/email has two rendered <tr> rows:
        Row A (full): cells[0] has exactly 2 direct <table> children
                      — table[0] = metadata header
                      — table[1] = body text (may contain base64 <img> in
                                   <span class="cmt_text">)
        Row B (meta): cells[0] has <img> + <span class="pst"> (skip)

    We only process Row A rows (2 direct table children).

    Each returned entry is in the canonical comment shape:
      {id, author, date, internal, body, images:[{mime, data}], attachments:[]}
    """
    comments = []
    for row in soup.find_all("tr"):
        cells = [c for c in row.find_all("td", recursive=False) if isinstance(c, Tag)]
        if not cells:
            continue
        cell0 = cells[0]

        # Identify full comment rows: exactly 2 direct <table> children
        direct_tables = [t for t in cell0.find_all("table", recursive=False)
                         if isinstance(t, Tag)]
        if len(direct_tables) != 2:
            continue

        header_text = _clean(direct_tables[0].get_text())
        body_text   = _clean(direct_tables[1].get_text())

        if not body_text:
            continue

        header_lower = header_text.lower()
        if not (header_lower.startswith("comment ") or header_lower.startswith("email ")):
            continue

        entry: dict = {
            "id":          "",
            "author":      "",
            "date":        "",
            "internal":    False,
            "body":        body_text,
            "images":      [],
            "attachments": [],
        }

        m_comment = _COMMENT_HDR_RE.match(header_text)
        m_email   = _EMAIL_HDR_RE.match(header_text)

        if m_comment:
            entry["id"]     = m_comment.group(1)
            entry["author"] = m_comment.group(2)
            entry["date"]   = m_comment.group(3).strip()
        elif m_email:
            entry["id"]     = m_email.group(1)
            entry["author"] = m_email.group(3)
            entry["date"]   = m_email.group(4).strip()
        else:
            entry["id"]     = "?"
            entry["author"] = ""

        # Inline base64 images embedded in comment body
        # (data:mime/type;base64,...) in <span class="cmt_text"> <img> tags.
        # Confirmed 2026-06-09: portal embeds screenshots directly this way.
        images = []
        for img_tag in direct_tables[1].find_all("img"):
            src = img_tag.get("src", "")
            if src.startswith("data:"):
                try:
                    meta, b64_data = src.split(",", 1)
                    mime = meta.split(":")[1].split(";")[0]
                    images.append({"mime": mime, "data": b64_data})
                except (ValueError, IndexError):
                    pass
        entry["images"] = images

        comments.append(entry)

    return comments
