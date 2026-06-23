"""Write scraped tradedesk ticket data to the tickets output dir as JSON + Markdown.
Files are already downloaded by the portal adapter; this module only references them.
"""
from __future__ import annotations
import json
from pathlib import Path

def save_ticket(data: dict, tickets_base: Path) -> None:
    tickets_base = Path(tickets_base)
    tickets_base.mkdir(parents=True, exist_ok=True)
    tid = data.get("ticket_id", "unknown")
    (tickets_base / f"ticket_{tid}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (tickets_base / f"ticket_{tid}.md").write_text(_to_markdown(data), encoding="utf-8")

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
            lines.append("")

    files = d.get("attachments") or []
    if files:
        lines += ["## Files", ""]
        for a in files:
            sp = a.get("saved_path"); name = a.get("filename") or (Path(sp).name if sp else "file")
            lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
        lines.append("")
    return "\n".join(lines)
