#!/usr/bin/env python3
"""
export_csv.py - Export yearly_stats from the AstroScanr SQLite database to
CSV, in the same format the dashboard has always consumed.

Usage:
    python3 export_csv.py
    python3 export_csv.py --db astroscanr.db --output docs/astroscanr-stats.csv
    python3 export_csv.py --journals all
    python3 export_csv.py --journals MNRAS,ApJ,A&A

Behavior:
    --journals not given   -> export the "all journals" rollup rows
                               (yearly_stats.journal IS NULL), one row per year.
    --journals all         -> export per-journal rows, one row per
                               (year, journal) combination.
    --journals X,Y,Z       -> export rollup rows, filtered to only years
                               where at least one paper came from journals
                               X, Y, or Z (still aggregated across all
                               journals, matching prior script behavior of
                               a single "rollup-shaped" CSV).

The output columns match the historical CSV format exactly, so the
dashboard (index.html / docs/) keeps working without changes:

    year,avg_authors,max_authors,pct_1author,pct_2author,pct_3author,
    pct_4author,pct_5plus,num_papers,num_unique_authors,
    citation_pct_1author
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from db_manager import AstroScanrDB

CSV_FIELDS = [
    "year",
    "avg_authors",
    "max_authors",
    "pct_1author",
    "pct_2author",
    "pct_3author",
    "pct_4author",
    "pct_5plus",
    "num_papers",
    "num_unique_authors",
    "citation_pct_1author",
]


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export yearly_stats from astroscanr.db to CSV."
    )
    parser.add_argument(
        "--db",
        default="astroscanr.db",
        help="Path to the SQLite database (default: astroscanr.db)",
    )
    parser.add_argument(
        "--output",
        default="docs/astroscanr-stats.csv",
        help="Path to write the CSV to (default: docs/astroscanr-stats.csv)",
    )
    parser.add_argument(
        "--journals",
        default=None,
        help=(
            "Optional journal filter. 'all' exports one row per "
            "year/journal combo. A comma-separated list (e.g. "
            "'MNRAS,ApJ') filters the rollup rows to years covered by "
            "those journals. Omit to export the plain 'all journals' "
            "rollup (default, matches historical behavior)."
        ),
    )
    return parser.parse_args(argv)


def row_to_csv_dict(row) -> dict:
    """Map a yearly_stats sqlite3.Row to the CSV field dict."""
    return {field: row[field] for field in CSV_FIELDS}


def export_rollup(db: AstroScanrDB, journal_filter: list[str] | None) -> list[dict]:
    """Export rollup rows (journal IS NULL), optionally restricted to
    years where at least one of `journal_filter` journals has papers."""
    rollup_rows = db.get_yearly_rollup()

    if journal_filter:
        # Restrict to years where at least one paper exists for one of
        # the requested journals.
        placeholders = ",".join("?" for _ in journal_filter)
        years_with_journal = {
            r[0]
            for r in db.conn.execute(
                f"SELECT DISTINCT year FROM papers WHERE journal IN ({placeholders})",
                journal_filter,
            ).fetchall()
        }
        rollup_rows = [r for r in rollup_rows if r["year"] in years_with_journal]

    return [row_to_csv_dict(r) for r in rollup_rows]


def export_all_journals(db: AstroScanrDB) -> list[dict]:
    """Export one row per (year, journal) combination (journal NOT NULL),
    ordered by year then journal."""
    rows = db.conn.execute(
        "SELECT * FROM yearly_stats WHERE journal IS NOT NULL "
        "ORDER BY year, journal"
    ).fetchall()
    out = []
    for r in rows:
        d = row_to_csv_dict(r)
        # Keep the journal column when exporting per-journal breakdowns so
        # rows are distinguishable; CSV_FIELDS + journal.
        d["journal"] = r["journal"]
        out.append(d)
    return out


def write_csv(rows: list[dict], output_path: Path, include_journal: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = CSV_FIELDS + (["journal"] if include_journal else [])
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv=None) -> int:
    args = parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"⚠️  Database not found: {db_path}", file=sys.stderr)
        return 1

    db = AstroScanrDB(db_path)
    try:
        if args.journals is None:
            rows = export_rollup(db, journal_filter=None)
            include_journal = False
        elif args.journals.strip().lower() == "all":
            rows = export_all_journals(db)
            include_journal = True
        else:
            journal_filter = [j.strip() for j in args.journals.split(",") if j.strip()]
            rows = export_rollup(db, journal_filter=journal_filter)
            include_journal = False
    finally:
        db.close()

    if not rows:
        print("⚠️  No yearly_stats rows found to export.", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    write_csv(rows, output_path, include_journal=include_journal)

    print(f"✅ Exported {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
