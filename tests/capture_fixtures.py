"""
One-time capture of real fixtures from help.contoso.example.
Run from the Knowledge Base root:
  scraper\\venv\\Scripts\\python.exe tests\\capture_fixtures.py
Saves real HTML pages and REST API responses into tests/fixtures/.
"""
import json
import urllib.request
from pathlib import Path

BASE = "https://help.contoso.example"
FIXTURES = Path(__file__).parent / "fixtures"

PAGES = {
    "tradedesk_real.html": f"{BASE}/display/releasenotes/Version+3.0.1.9",
    "web4_real.html":     f"{BASE}/display/ReleaseNotesWeb4/Version+4.0.3.0",
    "saleshub_real.html":  f"{BASE}/display/SHReleaseNotes/SalesHub+WEB+Version+2.0.2.1",
}
REST = {
    "tradedesk_rest.json": "releasenotes",
    "web4_rest.json":     "ReleaseNotesWeb4",
    "saleshub_rest.json":  "SHReleaseNotes",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 fixture-capture"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)

    for name, url in PAGES.items():
        print(f"Fetching page {url}")
        (FIXTURES / name).write_bytes(fetch(url))

    for name, space_key in REST.items():
        # Capture ALL pages (follow _links.next) into one combined results list,
        # mimicking what discovery will iterate over.
        combined = {"results": []}
        next_path = f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
        while next_path:
            data = json.loads(fetch(f"{BASE}{next_path}"))
            combined["results"].extend(data.get("results", []))
            nxt = data.get("_links", {}).get("next")
            next_path = nxt if nxt else None
        print(f"REST {space_key}: {len(combined['results'])} pages")
        (FIXTURES / name).write_text(json.dumps(combined, indent=2), encoding="utf-8")

    print("Fixtures captured.")


if __name__ == "__main__":
    main()
