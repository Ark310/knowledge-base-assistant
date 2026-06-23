"""Write scraped tradedesk ticket data to the tickets output dir as JSON + Markdown.

Files in the Files panel are already downloaded by the portal adapter; this module only
references those. Inline comment images arrive as base64 data URIs — they are decoded to
files here so the raw base64 never lands in the JSON.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path

_MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp",
}


def save_ticket(data: dict, tickets_base: Path) -> None:
    tickets_base = Path(tickets_base)
    tickets_base.mkdir(parents=True, exist_ok=True)
    tid = data.get("ticket_id", "unknown")
    _save_comment_images(data, tickets_base)  # mutates: base64 -> saved_path (no raw b64 in JSON)
    (tickets_base / f"ticket_{tid}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (tickets_base / f"ticket_{tid}.md").write_text(_to_markdown(data), encoding="utf-8")


def _save_comment_images(data: dict, tickets_base: Path) -> None:
    """Decode inline base64 comment images to files; replace raw data with saved_path.

    Mutates data["comments"][*]["images"] in place: {mime, data} -> {mime, saved_path}.
    Idempotent — entries already lacking raw "data" are passed through unchanged.
    """
    tid = data.get("ticket_id", "unknown")
    for c in data.get("comments") or []:
        imgs = c.get("images")
        if not imgs:
            continue
        cid = c.get("id", "x")
        adir = tickets_base / "attachments" / tid
        adir.mkdir(parents=True, exist_ok=True)
        resolved = []
        for n, im in enumerate(imgs):
            mime = im.get("mime", "image/png")
            b64 = im.get("data")
            if not b64:
                resolved.append({k: v for k, v in im.items() if k != "data"})
                continue
            ext = _MIME_EXT.get(mime, "bin")
            fp = adir / f"comment_{cid}_img{n}.{ext}"
            try:
                fp.write_bytes(base64.b64decode(b64))
                resolved.append({"mime": mime, "saved_path": str(fp)})
            except Exception:
                resolved.append({"mime": mime, "saved_path": None})
        c["images"] = resolved

def _f(lines, label, value):
    if value:
        lines.append(f"**{label}:** {value}")

def _to_markdown(d: dict) -> str:
    tid = d.get("ticket_id", "?")
    lines = [f"# Ticket {tid}: {d.get('title','')}", ""]
    for label, key in (("Product","product"),("Organization","organization"),("Priority","priority"),
                       ("Category","category"),("Severity","severity"),("Status","status"),
                       ("Assignee","assignee"),("CSQA Owner","csqa_owner"),
                       ("Created By","created_by"),("Created At","created_at"),
                       ("Awaiting Production Deployment","awaiting_production_deployment")):
        _f(lines, label, d.get(key))
    _f(lines, "URL", d.get("url"))
    _f(lines, "Scraped At", d.get("scraped_at"))
    lines.append("")

    res = d.get("resolution")
    if res and (res.get("text") or res.get("attachments")):
        lines += ["## Resolution", "", res.get("text", ""), ""]
        for a in res.get("attachments") or []:
            sp = a.get("saved_path"); name = a.get("label") or (Path(sp).name if sp else "file")
            lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
        lines.append("")

    comments = d.get("comments") or []
    if comments:
        lines += ["## Comments", ""]
        for c in comments:
            tag = " (internal)" if c.get("internal") else ""
            lines.append(f"### #{c.get('id','')} — {c.get('author','')} · {c.get('date','')}{tag}")
            lines.append("")
            if c.get("body"):
                lines.append(c["body"])
            for a in c.get("attachments") or []:
                sp = a.get("saved_path"); name = a.get("label") or (Path(sp).name if sp else "file")
                lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
            for im in c.get("images") or []:
                sp = im.get("saved_path")
                if sp:
                    lines.append(f"![image]({sp})")
            lines.append("")

    files = d.get("attachments") or []
    if files:
        lines += ["## Files", ""]
        for a in files:
            sp = a.get("saved_path"); name = a.get("filename") or (Path(sp).name if sp else "file")
            lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
        lines.append("")
    return "\n".join(lines)
