#!/usr/bin/env python3
"""
migrate_json_to_db.py - One-time migration of the legacy JSON paper cache
(data/historical_papers.json) into the new SQLite database.

Usage:
    python3 migrate_json_to_db.py
    python3 migrate_json_to_db.py --json data/historical_papers.json --db astroscanr.db

Behavior:
    - If the JSON cache doesn't exist, exits gracefully (nothing to do).
    - Otherwise loads it, inserts every paper via db.insert_papers(),
      recomputes yearly_stats for all years, prints a summary, and
      renames the JSON file to a `.bak` safety copy.

The legacy JSON cache is shaped like:
    {
        "<year>": {
            "<journal>": [
                {
                    "bibcode": str,
                    "authors": [str, ...],
                    "num_authors": int,
                    "citations": int,
                },
                ...
            ],
            ...
        },
        ...
    }

Note the legacy key is `citations`, while db_manager's `insert_papers`
expects `citation_count` — this script translates between the two.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from db_manager import AstroScanrDB


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate legacy JSON paper cache into astroscanr.db."
    )
    parser.add_argument(
        "--json",
        default="data/historical_papers.json",
        help="Path to the legacy JSON cache (default: data/historical_papers.json)",
    )
    parser.add_argument(
        "--db",
        default="astroscanr.db",
        help="Path to the SQLite database to create/populate (default: astroscanr.db)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip renaming the JSON cache to .json.bak after a successful migration.",
    )
    return parser.parse_args(argv)


def normalize_paper(paper: dict) -> dict:
    """Translate a legacy JSON paper record into the shape expected by
    AstroScanrDB.insert_papers (mainly: citations -> citation_count)."""
    return {
        "bibcode": paper.get("bibcode"),
        "authors": paper.get("authors", []),
        "num_authors": paper.get("num_authors"),
        "citation_count": paper.get("citation_count", paper.get("citations", 0)),
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    json_path = Path(args.json)

    if not json_path.exists():
        print(f"No JSON cache found at {json_path} — nothing to migrate.")
        return 0

    print(f"Loading JSON cache from {json_path} ...")
    try:
        with json_path.open() as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Failed to read/parse JSON cache: {e}", file=sys.stderr)
        return 1

    db = AstroScanrDB(args.db)

    total_papers_seen = 0
    total_inserted = 0
    journals_seen: set[str] = set()
    years_seen: set[int] = set()

    try:
        for year_str, journals in cache.items():
            try:
                year = int(year_str)
            except (TypeError, ValueError):
                print(f"⚠️  Skipping non-integer year key: {year_str!r}", file=sys.stderr)
                continue

            if not isinstance(journals, dict):
                print(f"⚠️  Skipping malformed year entry for {year_str!r}", file=sys.stderr)
                continue

            years_seen.add(year)

            for journal, papers_list in journals.items():
                if not isinstance(papers_list, list):
                    continue

                journals_seen.add(journal)
                total_papers_seen += len(papers_list)

                normalized = [normalize_paper(p) for p in papers_list]
                inserted = db.insert_papers(journal, year, normalized)
                total_inserted += inserted

        duplicates_skipped = total_papers_seen - total_inserted

        print("Computing yearly stats ...")
        rows_written = db.compute_and_insert_yearly_stats("all")

        print()
        print("=" * 60)
        print("✅ Migration complete")
        print("=" * 60)
        print(f"  {total_inserted:,} papers loaded (of {total_papers_seen:,} seen)")
        print(f"  {len(journals_seen)} unique journals")
        print(f"  {len(years_seen)} years covered")
        print(f"  {duplicates_skipped:,} duplicates skipped")
        print(f"  {rows_written} yearly_stats rows computed")
        print(f"  Database: {Path(args.db).resolve()}")
    finally:
        db.close()

    if not args.no_backup:
        backup_path = json_path.with_suffix(json_path.suffix + ".bak")
        try:
            json_path.rename(backup_path)
            print(f"  Old JSON cache renamed to {backup_path}")
        except OSError as e:
            print(f"⚠️  Could not rename JSON cache to backup: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
