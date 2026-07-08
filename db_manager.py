"""
db_manager.py - AstroScanr SQLite database layer.

Core abstraction over the AstroScanr SQLite store. Everything else in the
pipeline (fetcher, analysis, checkpointing) depends on this module, so it is
kept dependency-free (stdlib sqlite3 only) and defensively coded.

Schema
------
papers          One row per paper, deduplicated on `bibcode`.
yearly_stats    Cached aggregates, one row per (year, journal) combination
                (journal may be NULL to represent an "all journals" rollup
                for that year).
checkpoint      Single-row (in practice) progress tracker for resumable
                fetch runs across journals.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
#
# NOTE: The UNIQUE(...) table constraints must come *before* any trailing
# column definitions in SQLite DDL (a column definition cannot follow a
# table-level constraint). The schema below is logically identical to the
# spec in the task description, with `created_at` reordered to be a normal
# column defined alongside the other columns, and UNIQUE placed last as a
# table-level constraint.

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY,
  bibcode TEXT UNIQUE NOT NULL,
  year INTEGER NOT NULL,
  journal TEXT NOT NULL,
  num_authors INTEGER NOT NULL,
  authors TEXT NOT NULL,
  citation_count INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS yearly_stats (
  id INTEGER PRIMARY KEY,
  year INTEGER NOT NULL,
  journal TEXT,
  avg_authors REAL,
  max_authors INTEGER,
  num_papers INTEGER,
  num_unique_authors INTEGER,
  pct_1author REAL,
  pct_2author REAL,
  pct_3author REAL,
  pct_4author REAL,
  pct_5plus REAL,
  citation_pct_1author REAL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(year, journal)
);

CREATE TABLE IF NOT EXISTS checkpoint (
  id INTEGER PRIMARY KEY,
  next_journal_idx INTEGER,
  completed_journals TEXT,
  last_run DATETIME,
  requests_used INTEGER
);

CREATE INDEX IF NOT EXISTS idx_papers_journal ON papers(journal);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_yearly_stats_year ON yearly_stats(year);
"""


def _author_bucket_case(column: str) -> str:
    """Return a SQL CASE expression bucketing `column` (author count) into
    the 1/2/3/4/5+ buckets used by yearly_stats percentage columns."""
    return f"""
        CASE
            WHEN {column} = 1 THEN '1'
            WHEN {column} = 2 THEN '2'
            WHEN {column} = 3 THEN '3'
            WHEN {column} = 4 THEN '4'
            ELSE '5plus'
        END
    """


class AstroScanrDB:
    """SQLite-backed store for AstroScanr paper data, yearly aggregates,
    and fetch checkpoints.

    Usage:
        db = AstroScanrDB("/tmp/astroscanr/astroscanr.db")
        db.init_schema()
        db.insert_papers("ApJ", 2020, [...])
        db.compute_and_insert_yearly_stats("all")
    """

    def __init__(self, db_path: Union[str, Path]):
        """Connect to (or create) the SQLite database at `db_path`.

        Parent directories are created if missing. Foreign keys are not
        used in this schema, but WAL mode is enabled for better concurrent
        read/write behaviour during long fetch runs.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

        self.init_schema()

    # ------------------------------------------------------------------
    # Context manager support (optional convenience)
    # ------------------------------------------------------------------
    def __enter__(self) -> "AstroScanrDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying connection."""
        self.conn.close()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager yielding a cursor and committing on success,
        rolling back on error."""
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def init_schema(self) -> None:
        """Create all tables/indexes if they do not already exist.
        Safe to call repeatedly (idempotent)."""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Papers
    # ------------------------------------------------------------------
    def insert_papers(
        self, journal: str, year: int, papers_list: Sequence[dict]
    ) -> int:
        """Batch-insert papers for a given journal/year fetch batch.

        `papers_list` items look like:
            {
                "bibcode": str,
                "year": int,             # optional; falls back to `year` arg
                "journal": str,          # optional; falls back to `journal` arg
                "num_authors": int,
                "authors": [str, ...],   # list, will be JSON-encoded
                "citation_count": int,   # optional, default 0
            }

        Duplicates (same bibcode) are silently skipped via INSERT OR IGNORE
        (bibcode has a UNIQUE constraint).

        Returns the number of rows actually inserted (excludes skipped
        duplicates).
        """
        rows = []
        for p in papers_list:
            bibcode = p.get("bibcode")
            if not bibcode:
                # Can't dedupe / identify a paper without a bibcode; skip it.
                continue

            authors = p.get("authors", [])
            if not isinstance(authors, str):
                authors_json = json.dumps(authors)
            else:
                # Already a JSON string (or plain string) - store as-is.
                authors_json = authors

            num_authors = p.get("num_authors")
            if num_authors is None:
                try:
                    num_authors = len(json.loads(authors_json))
                except (json.JSONDecodeError, TypeError):
                    num_authors = 0

            rows.append(
                (
                    bibcode,
                    p.get("year", year),
                    p.get("journal", journal),
                    num_authors,
                    authors_json,
                    p.get("citation_count", 0),
                )
            )

        if not rows:
            return 0

        with self._cursor() as cur:
            cur.executemany(
                """
                INSERT OR IGNORE INTO papers
                    (bibcode, year, journal, num_authors, authors, citation_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = cur.rowcount if cur.rowcount is not None else 0

        return inserted

    def get_papers(
        self, journal: Optional[str] = None, year: Optional[int] = None
    ) -> list[sqlite3.Row]:
        """Query papers, optionally filtered by journal and/or year.

        Returns a list of sqlite3.Row objects (dict-like access by column
        name, e.g. row["bibcode"]).
        """
        query = "SELECT * FROM papers WHERE 1=1"
        params: list[Any] = []

        if journal is not None:
            query += " AND journal = ?"
            params.append(journal)

        if year is not None:
            query += " AND year = ?"
            params.append(year)

        query += " ORDER BY year, journal, bibcode"

        cur = self.conn.execute(query, params)
        return cur.fetchall()

    def papers_count(
        self, journal: Optional[str] = None, year: Optional[int] = None
    ) -> int:
        """Return the count of papers, optionally filtered by
        journal/year. Handy for debugging and sanity checks."""
        query = "SELECT COUNT(*) FROM papers WHERE 1=1"
        params: list[Any] = []

        if journal is not None:
            query += " AND journal = ?"
            params.append(journal)

        if year is not None:
            query += " AND year = ?"
            params.append(year)

        cur = self.conn.execute(query, params)
        return cur.fetchone()[0]

    # ------------------------------------------------------------------
    # Yearly stats
    # ------------------------------------------------------------------
    def compute_and_insert_yearly_stats(
        self, year_or_all: Union[int, str] = "all"
    ) -> int:
        """Compute yearly aggregate stats from the `papers` table and
        upsert them into `yearly_stats`.

        `year_or_all`:
            - int: compute stats only for that year.
            - "all" (default): compute stats for every distinct year
              present in `papers`.

        For each year, two kinds of rows are produced:
            1. Per-journal rows (journal = <journal name>)
            2. An "all journals" rollup row for that year (journal = NULL)

        Stats computed per group:
            - avg_authors: mean num_authors
            - max_authors: max num_authors
            - num_papers: count of papers
            - num_unique_authors: count of distinct author names across
              the group's papers (authors JSON arrays are unioned)
            - pct_1author .. pct_5plus: percentage of papers with exactly
              1/2/3/4/5+ authors
            - citation_pct_1author: percentage of *total citations* in the
              group that come from single-author papers (0 if the group
              has zero total citations)

        Existing rows for the same (year, journal) are replaced (upsert),
        so this method is safe to re-run after new papers are fetched.

        Returns the number of (year, journal-or-rollup) rows written.
        """
        if year_or_all == "all" or year_or_all is None:
            years = [
                r[0]
                for r in self.conn.execute(
                    "SELECT DISTINCT year FROM papers ORDER BY year"
                ).fetchall()
            ]
        else:
            years = [int(year_or_all)]

        rows_written = 0

        for year in years:
            # Distinct journals present for this year, plus a `None`
            # sentinel representing the "all journals" rollup.
            journals = [
                r[0]
                for r in self.conn.execute(
                    "SELECT DISTINCT journal FROM papers WHERE year = ?",
                    (year,),
                ).fetchall()
            ]
            groups: list[Optional[str]] = [*journals, None]

            for journal in groups:
                stats = self._compute_stats_for_group(year, journal)
                if stats is None:
                    continue
                self._upsert_yearly_stats(year, journal, stats)
                rows_written += 1

        return rows_written

    def _compute_stats_for_group(
        self, year: int, journal: Optional[str]
    ) -> Optional[dict]:
        """Compute the stats dict for a single (year, journal) group.
        `journal=None` means "all journals" for that year. Returns None
        if the group has no papers."""
        if journal is None:
            paper_rows = self.conn.execute(
                "SELECT num_authors, authors, citation_count "
                "FROM papers WHERE year = ?",
                (year,),
            ).fetchall()
        else:
            paper_rows = self.conn.execute(
                "SELECT num_authors, authors, citation_count "
                "FROM papers WHERE year = ? AND journal = ?",
                (year, journal),
            ).fetchall()

        num_papers = len(paper_rows)
        if num_papers == 0:
            return None

        num_authors_list = [r["num_authors"] for r in paper_rows]
        citation_list = [r["citation_count"] or 0 for r in paper_rows]

        avg_authors = sum(num_authors_list) / num_papers
        max_authors = max(num_authors_list)

        # Unique authors across the group (union of all author names).
        unique_authors: set[str] = set()
        for r in paper_rows:
            try:
                names = json.loads(r["authors"]) if r["authors"] else []
            except (json.JSONDecodeError, TypeError):
                names = []
            if isinstance(names, list):
                unique_authors.update(names)

        def pct(n: int) -> float:
            return 100.0 * n / num_papers

        n_1 = sum(1 for n in num_authors_list if n == 1)
        n_2 = sum(1 for n in num_authors_list if n == 2)
        n_3 = sum(1 for n in num_authors_list if n == 3)
        n_4 = sum(1 for n in num_authors_list if n == 4)
        n_5plus = sum(1 for n in num_authors_list if n >= 5)

        total_citations = sum(citation_list)
        citations_1author = sum(
            c
            for n, c in zip(num_authors_list, citation_list)
            if n == 1
        )
        citation_pct_1author = (
            100.0 * citations_1author / total_citations
            if total_citations > 0
            else 0.0
        )

        return {
            "avg_authors": avg_authors,
            "max_authors": max_authors,
            "num_papers": num_papers,
            "num_unique_authors": len(unique_authors),
            "pct_1author": pct(n_1),
            "pct_2author": pct(n_2),
            "pct_3author": pct(n_3),
            "pct_4author": pct(n_4),
            "pct_5plus": pct(n_5plus),
            "citation_pct_1author": citation_pct_1author,
        }

    def _upsert_yearly_stats(
        self, year: int, journal: Optional[str], stats: dict
    ) -> None:
        """Insert or replace the yearly_stats row for (year, journal)."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO yearly_stats (
                    year, journal, avg_authors, max_authors, num_papers,
                    num_unique_authors, pct_1author, pct_2author,
                    pct_3author, pct_4author, pct_5plus,
                    citation_pct_1author
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(year, journal) DO UPDATE SET
                    avg_authors=excluded.avg_authors,
                    max_authors=excluded.max_authors,
                    num_papers=excluded.num_papers,
                    num_unique_authors=excluded.num_unique_authors,
                    pct_1author=excluded.pct_1author,
                    pct_2author=excluded.pct_2author,
                    pct_3author=excluded.pct_3author,
                    pct_4author=excluded.pct_4author,
                    pct_5plus=excluded.pct_5plus,
                    citation_pct_1author=excluded.citation_pct_1author
                """,
                (
                    year,
                    journal,
                    stats["avg_authors"],
                    stats["max_authors"],
                    stats["num_papers"],
                    stats["num_unique_authors"],
                    stats["pct_1author"],
                    stats["pct_2author"],
                    stats["pct_3author"],
                    stats["pct_4author"],
                    stats["pct_5plus"],
                    stats["citation_pct_1author"],
                ),
            )

    def get_yearly_stats(
        self, year: Optional[int] = None, journal: Optional[str] = None
    ) -> list[sqlite3.Row]:
        """Convenience query over yearly_stats. `journal=None` in the
        filter is ignored (returns both journal rows and the rollup row)
        unless explicitly querying for the rollup - see get_yearly_rollup.
        """
        query = "SELECT * FROM yearly_stats WHERE 1=1"
        params: list[Any] = []

        if year is not None:
            query += " AND year = ?"
            params.append(year)

        if journal is not None:
            query += " AND journal = ?"
            params.append(journal)

        query += " ORDER BY year, journal"

        return self.conn.execute(query, params).fetchall()

    def get_yearly_rollup(self, year: Optional[int] = None) -> list[sqlite3.Row]:
        """Return only the 'all journals' rollup rows (journal IS NULL),
        optionally filtered to a single year."""
        query = "SELECT * FROM yearly_stats WHERE journal IS NULL"
        params: list[Any] = []

        if year is not None:
            query += " AND year = ?"
            params.append(year)

        query += " ORDER BY year"

        return self.conn.execute(query, params).fetchall()

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------
    def save_checkpoint(
        self,
        idx: int,
        journals: Iterable[str],
        requests: int,
    ) -> None:
        """Save (upsert) fetch progress.

        Since checkpointing tracks a single ongoing fetch run, this keeps
        exactly one row (id=1) and replaces it each call.

        `idx`: index of the next journal to process.
        `journals`: iterable of journal names already completed.
        `requests`: number of API requests used so far in this run.
        """
        completed_journals_json = json.dumps(list(journals))
        last_run = datetime.now(timezone.utc).isoformat()

        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO checkpoint (id, next_journal_idx, completed_journals,
                                         last_run, requests_used)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    next_journal_idx=excluded.next_journal_idx,
                    completed_journals=excluded.completed_journals,
                    last_run=excluded.last_run,
                    requests_used=excluded.requests_used
                """,
                (idx, completed_journals_json, last_run, requests),
            )

    def get_checkpoint(self) -> Optional[dict]:
        """Read the current checkpoint. Returns None if no checkpoint has
        been saved yet, otherwise a dict:
            {
                "next_journal_idx": int,
                "completed_journals": [str, ...],
                "last_run": str (ISO datetime),
                "requests_used": int,
            }
        """
        row = self.conn.execute(
            "SELECT next_journal_idx, completed_journals, last_run, requests_used "
            "FROM checkpoint WHERE id = 1"
        ).fetchone()

        if row is None:
            return None

        try:
            completed = json.loads(row["completed_journals"]) if row["completed_journals"] else []
        except (json.JSONDecodeError, TypeError):
            completed = []

        return {
            "next_journal_idx": row["next_journal_idx"],
            "completed_journals": completed,
            "last_run": row["last_run"],
            "requests_used": row["requests_used"],
        }
