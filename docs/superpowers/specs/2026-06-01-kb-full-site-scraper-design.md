# Full-Site KB Scraper — Design Spec
**Date:** 2026-06-01  
**Status:** Approved  

---

## Overview

Extend the existing Contoso KB Scraper GUI (currently v1, release notes only) with a second tab — v2 — that scrapes the entire `help.contoso.example` Confluence site. The output feeds a chatbot knowledge base. v1 and v2 run independently with completely separate state, controls, and library output.

---

## Scope

### Spaces to scrape (34 total, grouped by product family)

> **Note:** The "FIX Protocol/Distribution Layer" tile visible on the TradeDesk KB category page has no dedicated Confluence space in the REST API — its content is distributed across existing TradeDesk spaces and will be captured as part of those.

**TradeDesk KB**
| Space Key | Name |
|---|---|
| `SA` | System Administration |
| `parameters` | Parameters |
| `Finance` | Finance |
| `Dealing` | Dealing |
| `compliance` | Compliance |
| `Reports` | Reports |

**Web 2.0 KB**
| Space Key | Name |
|---|---|
| `administration` | Administration |
| `beneficiaries` | Beneficiaries |
| `BookingDeals` | Booking Deals |
| `dealinghistory` | Dealing History |
| `documents` | Documents |
| `GettingStarted` | Getting Started |
| `howto` | How To's |
| `MyAccount` | My Account |
| `payments` | Payments |

**Web 4.0 KB**
| Space Key | Name |
|---|---|
| `BookingDealsWeb4` | Booking Deals |
| `DealingHistoryWeb4` | Dealing History |
| `MyAccountWeb4` | My Account |
| `PaymentsWeb4` | Payments |
| `RecipientsWeb4` | Recipients |

**TradeDesk API KB**
| Space Key | Name |
|---|---|
| `Functions` | API Functions |
| `GS` | Getting Started |
| `API25ReleaseNotes` | API 2.5 Release Notes |
| `apireleasenotes` | Release Notes |
| `RestAPIReleaseNotes` | REST API Release Notes |

**SalesHub KB**
| Space Key | Name |
|---|---|
| `SHGettingStarted` | Getting Started |
| `SFFormManagement` | Form Management |
| `SFHowTo` | How To's |
| `SFOpenForms` | Open Form |
| `SFUserAccessControl` | User Access Control |
| `SHAPIReleaseNotes` | SalesHub API Release Notes |
| `SFReleaseNotes` | Release Notes |

**Other**
| Space Key | Name |
|---|---|
| `FBD` | Form Builder Docs |
| `WebReleaseNotes` | Web Release Notes |

**Explicitly excluded:**
- `TrainingVideos` — YouTube embeds only, no useful text
- `rwlayoutkey` — theme/layout config, not content
- `releasenotes`, `ReleaseNotesWeb4`, `SHReleaseNotes` — already handled by v1

---

## Architecture

### New files

| File | Purpose |
|---|---|
| `scraper/kb_config.py` | All 37 spaces with keys, display names, product family |
| `scraper/kb_discovery.py` | `discover_articles(space_key)` — enumerates all pages via REST API |
| `scraper/parsers/article.py` | Converts Confluence HTML → clean Markdown body |
| `scraper/writers/article_writer.py` | Saves `.json` + `.md` per article under `library/kb/` |
| `scraper/kb_engine.py` | Orchestrates v2 scraping; same callback/cancellation pattern as v1 |
| `scraper/kb_tab.py` | `KBTab(QWidget)` — the new GUI tab widget |

### Reused from v1 (unchanged)

| File | What's reused |
|---|---|
| `scraper/core.py` | `Browser`, `StateTracker` |
| `scraper/engine.py` | `EngineCallbacks`, `CancellationToken` |
| `scraper/discovery.py` | `default_http_get` |
| `scraper/parsers/universal.py` | `_parse_table`, `_find_content`, `_collapse_ws` |
| `scraper/config.py` | `BASE_URL`, `STATE_DIR`, `LIBRARY_BASE` |

### Modified

| File | Change |
|---|---|
| `scraper/gui.py` | Wrap existing UI in `QTabWidget`; Tab 1 = "v1 — Release Notes", Tab 2 = "v2 — Knowledge Base" (loads `KBTab`) |

---

## Discovery

`discover_articles(space_key)` follows the same pagination pattern as `discover_versions()`:

```
GET /rest/api/content?spaceKey={key}&type=page&limit=100&start=0
```

Returns all pages (no version-title filter). Each result yields:
```python
{"title": str, "url": str, "page_id": str, "slug": str}
```

`slug` is a filesystem-safe name derived from the title (lowercased, spaces → underscores, special chars stripped).

---

## Article Parser (`parsers/article.py`)

Converts rendered Confluence HTML to a clean Markdown string.

**Extracted elements:**

| HTML | Markdown output |
|---|---|
| `h1`–`h4` | `#` – `####` headings |
| `<ol>` / `<ul>` | `1.` / `-` lists (nested supported) |
| `<p>` | Plain text paragraph |
| `<table>` | Markdown table (via `_parse_table`) |
| Confluence info/note/warning panels | `> **Note:** ...` blockquote |
| `<pre>` / `<code>` | Fenced ` ``` ` code block |
| `<img>` | `![alt](confluence_image_url)` — links to live URL, no local download |

**Skipped:**
- Table of contents macros (`div.toc-macro`)
- Sidebar navigation
- Expand/collapse button chrome
- Page metadata (author, modified date, labels)

---

## Output Format

### JSON (`library/kb/{product}/{space_slug}/{article_slug}.json`)
```json
{
  "space_key": "SA",
  "space_name": "System Administration",
  "product": "tradedesk",
  "title": "How to Configure and Test Email",
  "url": "https://help.contoso.example/display/SA/...",
  "scraped_at": "2026-06-01T14:00:00",
  "screenshot": "library/kb/tradedesk/system_administration/screenshots/how_to_configure_and_test_email.png",
  "body_md": "## Instructions\n\n1. Go to System Administration..."
}
```

### Markdown (`library/kb/{product}/{space_slug}/{article_slug}.md`)
```markdown
---
title: How to Configure and Test Email
space: System Administration
product: tradedesk
url: https://help.contoso.example/display/SA/...
scraped_at: 2026-06-01T14:00:00
---

## Instructions

1. Go to System Administration → System Configuration → Manage Email Service.
...
```

### Library tree
```
library/
  kb/
    tradedesk/
      system_administration/
        screenshots/
        how_to_configure_and_test_email.json
        how_to_configure_and_test_email.md
      parameters/
      finance/
      dealing/
      compliance/
      reports/
    web2/
      administration/
      payments/
      booking_deals/
      dealing_history/
      documents/
      getting_started/
      how_to/
      my_account/
      beneficiaries/
    web4/
      booking_deals/
      dealing_history/
      my_account/
      payments/
      recipients/
    api/
      functions/
      getting_started/
      api_25_release_notes/
      release_notes/
      rest_api_release_notes/
    saleshub/
      getting_started/
      form_management/
      how_to/
      open_form/
      user_access_control/
      sh_api_release_notes/
      release_notes/
    other/
      form_builder_docs/
      web_release_notes/
```

---

## State Tracking

Separate state file: `scraper/state/scraped_articles.json`

Format mirrors `scraped_versions.json`:
```json
{
  "SA": {
    "how_to_configure_and_test_email": {
      "url": "https://...",
      "scraped_at": "2026-06-01T..."
    }
  }
}
```

Keyed by `space_key → article_slug`. Incremental runs skip already-scraped articles. Force re-scrape overrides this per-space or globally.

---

## GUI Tab 2 Layout

```
┌──────────────────────────────────────────────────────────────┐
│ [Validate]  [Discover/Refresh URLs]  [Rebuild Indexes]  [⏹ STOP] │
├──────────────────────────────────────────────────────────────┤
│ TradeDesk KB                                                   │
│  [Sys Admin] [Parameters] [Finance] [Dealing] [Compliance] [Reports] │
│ Web 2.0 KB                                                    │
│  [Admin] [Beneficiaries] [Booking Deals] [Dealing Hist] ...  │
│ Web 4.0 KB                                                    │
│  [Booking Deals] [Dealing Hist] [My Account] [Payments] [Recipients] │
│ API KB                                                        │
│  [Functions] [Getting Started] [API 2.5 RN] [RN] [REST RN]  │
│ SalesHub KB                                                    │
│  [Getting Started] [Form Mgmt] [How To's] [Open Form] ...    │
│ Other                                                         │
│  [Form Builder] [Web Release Notes]                          │
├──────────────────────────────────────────────────────────────┤
│ Progress: [████████░░░░] Scraping: SA — How to Setup 2FA (42/120) │
├──────────────────────────────────────────────────────────────┤
│ [Scrape ALL (incremental)]  [Force re-scrape ALL]            │
├──────────────────────────────────────────────────────────────┤
│ Log (coloured, same as v1)                                   │
└──────────────────────────────────────────────────────────────┘
```

Each space card shows: space name, articles discovered/new/skipped/failed, Scrape + Force checkboxes — mirrors v1 product cards exactly.

---

## Error Handling

- Failed pages logged with URL, retried once (same retry logic as v1 `Browser.navigate`)
- Empty pages (no extractable content) saved with empty `body_md` and flagged in log
- Spaces with 0 pages discovered logged as warnings, not failures
- Cancellation token checked between each article, same as v1

---

## Indexes

`kb_engine.rebuild_indexes()` generates:
- `library/kb/index.json` — flat list of all articles with title, space, product, url, scraped_at
- `library/kb/index.md` — Markdown table of all articles grouped by product family
