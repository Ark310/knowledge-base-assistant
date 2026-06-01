"""
Contoso KB Scraper V2.1 — CLI entry. Uses scraper.engine under the hood.
The GUI app (ContosoKBScraper.exe / scraper/gui.py) uses the same engine.
"""
from __future__ import annotations
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config import PRODUCTS, LOG_FILE
from scraper.engine import Engine, LoggingCallbacks, CancellationToken


def _setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


def main():
    parser = argparse.ArgumentParser(description="Contoso KB Release Notes Scraper V2.1 (CLI)")
    parser.add_argument("--product", choices=list(PRODUCTS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    _setup_logging()
    engine = Engine(callbacks=LoggingCallbacks(), cancel_token=CancellationToken())

    if args.validate:
        sys.exit(0 if engine.validate() else 1)
    if args.discover:
        engine.discover_and_update_config(); return
    if args.index_only:
        engine.rebuild_indexes(); return
    if args.all:
        engine.scrape_all(force=args.force); return
    if args.product:
        engine.scrape_product(args.product, force=args.force); return
    parser.print_help()


if __name__ == "__main__":
    main()
