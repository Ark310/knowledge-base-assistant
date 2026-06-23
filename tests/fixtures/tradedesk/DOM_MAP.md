# portal.contoso.example — DOM map (confirmed live 2026-06-22)

The portal is a Tailwind JS SPA. API (`portal.contoso.example`) is end-to-end AES-GCM
encrypted — scrape the **rendered DOM only**. Fixtures in this folder are SYNTHETIC
(structure-faithful, fake content) — no customer PII is ever committed.

> **CORRECTED 2026-06-23 (validated against CLEAN real DOM).** The Comments/Resolution/Files
> notes further down were first derived from a *corrupted* capture and are superseded by these:
> - **Comments**: card = nearest `div` whose classes ⊇ {rounded-lg, border, bg-white}
>   (e.g. `div.p-2.sm:p-4.rounded-lg.border.bg-white`), inside `div.space-y-2.sm:space-y-4`.
>   The `span.hidden` header holds only `comment {id} posted by ` — the **author is a separate
>   following `<a class="text-blue-600">`**. Body = `div.comment-html-content`. Internal =
>   a standalone element whose exact text is "Internal".
> - **Resolution**: text = `div.resolution-container div.post-content` (NOT `div.ql-editor`,
>   which is the empty edit form). Resolution file = icon `button[title*="Download"]`.
> - **Files panel**: filename in `p.text-sm.break-words`; download = icon
>   `button[title*="Download"]` (the `title` value carries literal quotes — use substring).
>   Do NOT count the comment list's text-"Download" buttons.
> - **Capture cleanly via base64** — `browser_evaluate` `filename` JSON-escapes raw HTML and
>   breaks CSS class selectors. See `.wolf/cerebrum.md` for the full note.

## Login (`/login`) — `login.html`
- `input` Username (placeholder/aria "Username"), `input[type=password]` Password.
- Submit `button` text "Sign In", **disabled until both fields filled** (JS-gated).
- Login page has NO `button.floating-dropdown-btn`.

## Ticket detail (`/tickets/{id}/edit`) — `ticket_detail.html`
- Ready signal: `document.title` → `Ticket ID {id} - {org} - {title}`.
- Header: `span.text-md` = `Ticket # {id}`; title in a sibling; `Created MM/DD/YYYY by {user}` text nearby.
- **Fields = `button.floating-dropdown-btn`**, each with `span.floating-dropdown-label`
  (label text + a `span.text-red-500` "*") and `span.floating-dropdown-value` (value).
  **Extract by LABEL (dedupe, first wins)** — fields render TWICE (`header_bg_*` set and
  `bg_*` set), and CSQA Owner's id is the literal `"header_CSQA Owner"`/`"CSQA Owner"`.
  Labels → keys: Organization→organization, Project→product, Priority→priority,
  Category→category, Severity→severity, Status→status, Assigned to→assignee, CSQA Owner→csqa_owner.
- `input[type=checkbox]` "Awaiting Production Deployment".
- **Comments**: container `div.space-y-2` → one `div.p-2` card per comment (11 live).
  Card → `div.flex` → (`span.relative` avatar, `div.flex-1` content). Full header
  `comment {id} posted by {Name}` is in a **`span.hidden`** (visible `span.truncate` is cut off —
  read the hidden span). `Internal` badge text present when internal-only. Date text
  `Mon DD, YYYY at H:MM AM/PM, N ago`. Body = `<p>` paragraphs. **Attachment** = `button.inline-flex`
  text "Download" inside the card's `div.mt-3`; filename in a nearby `div.min-w-0`/`.filename`.
- Sub-view nav: `button.sidebar-menu-btn` (`Ticket`, `Resolve N`, `Files N`, …) — click by text.

## Resolution (Resolve sub-view) — `resolution.html`
- `div.resolution-container` scopes the resolution. Text = `div.simple-rich-text-editor-container`
  → `div.ql-editor` `<p>`s. Upload control `input#attachmentFile` (ignore). Resolution file =
  `button.inline-flex` "Download" inside `div.resolution-container`. Comments remain rendered too.

## Files (Files sub-view) — `files.html`
- File cards (`div.border-2`) each: name in `div.min-w-0`/`.filename` + `button.inline-flex` "Download".

## Not-found
- Navigating to a missing ticket REDIRECTS to `/bugs` (title "Tickets - Support Portal").
  Detect: no `button.floating-dropdown-btn` AND no `Ticket #` text. Adapter also checks post-nav URL.

## Mutating controls — NEVER click while scraping
`Update Ticket`, `Park`, `Post Comment`, `Track Time`, field dropdowns. `Resolve`/`Files`/`Ticket`
sub-view buttons are read-only view switches (safe).
