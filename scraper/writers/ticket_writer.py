# scraper/writers/ticket_writer.py
"""Write scraped ticket data to library/tickets/ as JSON + Markdown."""
from __future__ import annotations
import base64
import json
from pathlib import Path

# Inline base64 images found in comment bodies (v3.1)
_MIME_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg":  "jpg",
    "image/png":  "png",
    "image/gif":  "gif",
    "image/webp": "webp",
    "image/bmp":  "bmp",
}


def save_ticket(data: dict, tickets_base: Path) -> None:
    """Write ticket_{id}.json and ticket_{id}.md to tickets_base.

    Attachment images embedded in comment bodies are decoded from base64,
    saved as files under attachments/{ticket_id}/, and the raw base64 is
    replaced with the saved file path before the JSON is written.
    """
    tid = data.get("ticket_id", "unknown")
    tickets_base.mkdir(parents=True, exist_ok=True)
    _save_attachments(data, tickets_base)   # mutates data in-place (base64 → paths)
    (tickets_base / f"ticket_{tid}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (tickets_base / f"ticket_{tid}.md").write_text(
        _to_markdown(data), encoding="utf-8"
    )


def _save_attachments(data: dict, tickets_base: Path) -> None:
    """Decode base64 comment images, save as files, replace raw data with paths.

    Mutates data["comments"][*]["attachment_images"] in-place:
    {mime, data} → {mime, saved_path}. Raw base64 is never written to disk.
    """
    tid = data.get("ticket_id", "unknown")
    for comment in data.get("comments") or []:
        images = comment.get("attachment_images")
        if not images:
            continue
        comment_id = comment.get("id", "unknown")
        attach_dir = tickets_base / "attachments" / tid
        attach_dir.mkdir(parents=True, exist_ok=True)
        resolved = []
        for n, img in enumerate(images):
            mime      = img.get("mime", "image/jpeg")
            ext       = _MIME_EXT.get(mime, "bin")
            file_path = attach_dir / f"comment_{comment_id}_{n}.{ext}"
            try:
                file_path.write_bytes(base64.b64decode(img["data"]))
                resolved.append({"mime": mime, "saved_path": str(file_path)})
            except Exception:
                resolved.append({"mime": mime, "saved_path": None})
        comment["attachment_images"] = resolved


def _to_markdown(d: dict) -> str:
    tid   = d.get("ticket_id", "?")
    title = d.get("title", "")
    lines = [f"# Ticket {tid}: {title}", ""]

    # Core identity
    _f(lines, "Ticket ID",    d.get("ticket_id"))
    _f(lines, "Product",      d.get("product"))
    _f(lines, "Module",       d.get("module"))
    _f(lines, "Sprint",       d.get("sprint"))
    _f(lines, "Priority",     d.get("priority"))
    _f(lines, "Severity",     d.get("severity"))
    _f(lines, "Organization", d.get("organization"))
    _f(lines, "Category",     d.get("category"))
    _f(lines, "Tags",         d.get("tags"))
    lines.append("")

    # People & workflow
    _f(lines, "Assignee",      d.get("assignee"))
    _f(lines, "SQA Assignee",  d.get("sqa_assignee"))
    _f(lines, "CSQA Owner",    d.get("csqa_owner"))
    _f(lines, "Created By",    d.get("created_by"))
    _f(lines, "Created At",    d.get("created_at"))
    _f(lines, "Status",        d.get("status"))
    _f(lines, "Total Status",  d.get("total_status"))
    _f(lines, "Scope Status",  d.get("scope_status"))
    lines.append("")

    # QA signoffs
    _f(lines, "SITE1 QA Signoff", d.get("site1_qa_signoff"))
    _f(lines, "SITE2 QA Signoff", d.get("site2_qa_signoff"))
    lines.append("")

    # Effort & dates
    _f(lines, "Dev Estimate Hrs",               d.get("dev_estimate_hrs"))
    _f(lines, "QA Estimate Hrs",                d.get("qa_estimate_hrs"))
    _f(lines, "Dev Actual Hrs",                 d.get("dev_actual_hrs"))
    _f(lines, "QA Actual Hrs",                  d.get("qa_actual_hrs"))
    _f(lines, "CSQA Actual Hrs",                d.get("csqa_actual_hrs"))
    _f(lines, "Other Actual Hrs",               d.get("other_actual_hrs"))
    _f(lines, "Estimate Start Date",            d.get("estimate_start_date"))
    _f(lines, "Estimate Dev End Date",          d.get("estimate_dev_end_date"))
    _f(lines, "Estimate QA Start Date",         d.get("estimate_qa_start_date"))
    _f(lines, "Estimated QA Completion Date",   d.get("estimated_qa_completion_date"))
    _f(lines, "Estimated Client Delivery Date", d.get("estimated_client_delivery_date"))
    _f(lines, "Internal Target Date",           d.get("internal_target_date"))
    _f(lines, "Delay Count",                    d.get("delay_count"))
    _f(lines, "Delay Days",                     d.get("delay_days"))
    lines.append("")

    # Tracking
    _f(lines, "TFS ID",                        d.get("tfs_id"))
    _f(lines, "Release Ver",                   d.get("release_ver"))
    _f(lines, "Is Parked",                     d.get("is_parked"))
    _f(lines, "Awaiting Production Deployment", d.get("awaiting_production_deployment"))
    _f(lines, "Environment Details",           d.get("environment_details"))
    _f(lines, "Type",                          d.get("ticket_type"))
    _f(lines, "Deployment",                    d.get("deployment"))
    lines.append("")

    # Links
    _f(lines, "URL",            d.get("url"))
    _f(lines, "Resolution URL", d.get("resolution_url"))
    _f(lines, "Scraped At",     d.get("scraped_at"))
    lines.append("")

    # Resolution
    if d.get("resolution"):
        lines += ["## Resolution", "", d["resolution"], ""]

    # Comments and emails (thread history)
    comments = d.get("comments") or []
    if comments:
        lines += ["## Comments & Emails", ""]
        for c in comments:
            ctype  = c.get("type", "comment").title()
            author = c.get("author", "unknown")
            date   = c.get("date", "")
            cid    = c.get("id", "")
            to_    = c.get("to", "")
            body   = c.get("body", "")

            if ctype.lower() == "email" and to_:
                lines.append(f"### {ctype} #{cid} — {author} → {to_} on {date}")
            else:
                lines.append(f"### {ctype} #{cid} — {author} on {date}")
            lines.append("")
            if body:
                lines.append(body)
            for img in c.get("attachment_images") or []:
                saved = img.get("saved_path")
                if saved:
                    lines.append(f"![attachment]({saved})")
            lines.append("")

    return "\n".join(lines)


def _f(lines: list, label: str, value: str | None) -> None:
    if value:
        lines.append(f"**{label}:** {value}")
