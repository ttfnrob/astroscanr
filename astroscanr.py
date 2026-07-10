#!/usr/bin/env python3
"""
AstroScanr: Authorship Patterns in Astronomical Literature

This script fetches data from the NASA ADS API for the main astronomy journals
(MNRAS, ApJ, A&A, etc.) and generates plots showing how authorship has evolved.

Features:
- SQLite-backed storage: efficient, queryable, no 50MB JSON files
- Checkpoint-based resumption: gracefully handles API rate limits, resumes next day
- Daily incremental builds: fetches one journal per day until rate-limited
- Weekly updates: once cache is built, weekly runs only fetch current year

Usage:
    export ADS_API_KEY="your-token-here"
    python3 astroscanr.py                    # Daily incremental (resumes from checkpoint)
    python3 astroscanr.py --current-year-only MNRAS ApJ  # Weekly: current year only
    python3 astroscanr.py --full-history     # Force full historical rebuild
"""

import requests
import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
matplotlib.rcParams['figure.max_open_warning'] = 0
import matplotlib.pyplot as plt
plt.ioff()
import numpy as np
from collections import defaultdict
import pandas as pd
import sys
import os
import datetime
import time

# Import SQLite database layer
from db_manager import AstroScanrDB

# NASA ADS API endpoint
ADS_API_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_API_KEY = os.environ.get("ADS_API_KEY", "")

# Astronomy journals: ordered by founding year (oldest first)
JOURNALS = ["AN", "MNRAS", "AJ", "ApJ", "PASP", "Icarus", "SolPh", "A&A", "ApJL", "PASA", "MNRASLetters", "NatAs", "OJA"]

# Fetch ALL years
CURRENT_YEAR = datetime.datetime.now().year
ALL_YEARS = list(range(1827, CURRENT_YEAR + 1))

# Database file
DB_FILE = "astroscanr.db"

MIN_REQUEST_INTERVAL = 1.0
RATE_LIMIT_THRESHOLD = 4500
REQUEST_TIMEOUT = 60  # Increased from 30s to 60s
MAX_RETRIES = 3
RETRY_DELAY = 2.0

def fetch_papers_by_year(journal, year, requests_used, skip_existing=True):
    """Fetch papers for a specific journal and year from NASA ADS."""
    if not ADS_API_KEY:
        print("ERROR: ADS_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)
    
    time.sleep(MIN_REQUEST_INTERVAL)
    
    # Query: papers in journal for given year (use bibstem shorthand)
    query = f'bibstem:{journal} AND year:{year}'
    
    params = {
        'q': query,
        'rows': 200,
        'fl': 'bibcode,year,author,citation_count,author_count',
        'start': 0,
    }
    
    headers = {'Authorization': f'Bearer {ADS_API_KEY}'}
    
    papers = []
    start = 0
    
    while True:
        params['start'] = start
        retry_count = 0
        success = False
        
        while retry_count < MAX_RETRIES and not success:
            try:
                r = requests.get(ADS_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
                if r.status_code == 401:
                    print(f"  ❌ {journal} {year}: HTTP 401 Unauthorized — check ADS_API_KEY")
                    return papers, requests_used
                elif r.status_code == 429:
                    print(f"  ⚠️ {journal} {year}: HTTP 429 Rate Limited")
                    return papers, requests_used
                elif r.status_code != 200:
                    print(f"  ⚠️ {journal} {year}: HTTP {r.status_code}")
                    break
                
                data = r.json()
                requests_used += 1
                success = True
                
                if 'response' not in data or 'docs' not in data['response']:
                    break
                
                docs = data['response']['docs']
                if not docs:
                    break
                
                for doc in docs:
                    # API field is 'author' not 'authors'
                    authors = doc.get('author', [])
                    num_authors = len(authors) if authors else doc.get('author_count', 0)
                    papers.append({
                        'bibcode': doc['bibcode'],
                        'year': doc['year'],
                        'journal': journal,
                        'num_authors': num_authors,
                        'authors': json.dumps(authors),
                        'citation_count': doc.get('citation_count', 0),
                    })
                
                # Check if there are more results
                if len(docs) < 200:
                    break
                
                start += 200
            
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count < MAX_RETRIES:
                    wait_time = RETRY_DELAY * (2 ** (retry_count - 1))  # Exponential backoff
                    print(f"  ⏳ {journal} {year}: Timeout (retry {retry_count}/{MAX_RETRIES} in {wait_time}s)")
                    time.sleep(wait_time)
                else:
                    print(f"  ⚠️ {journal} {year}: Timeout after {MAX_RETRIES} retries")
                    break
            
            except Exception as e:
                print(f"  ⚠️ {journal} {year}: {e}")
                break
        
        if not success:
            break
    
    return papers, requests_used

def fetch_incremental(db, journals_to_fetch, years_to_fetch=None):
    """Fetch papers incrementally, inserting into database."""
    if years_to_fetch is None:
        years_to_fetch = ALL_YEARS
    
    checkpoint = db.get_checkpoint()
    requests_used = checkpoint['requests_used'] if checkpoint else 0
    
    papers_fetched = 0
    
    for journal in journals_to_fetch:
        for year in years_to_fetch:
            if requests_used >= RATE_LIMIT_THRESHOLD:
                print(f"⚠️ Rate limit threshold ({RATE_LIMIT_THRESHOLD}) reached. Stopping.")
                db.save_checkpoint(journals_to_fetch.index(journal), journals_to_fetch[:journals_to_fetch.index(journal)], requests_used)
                return papers_fetched
            
            papers, requests_used = fetch_papers_by_year(journal, year, requests_used)
            if papers:
                db.insert_papers(journal, year, papers)
                papers_fetched += len(papers)
    
    return papers_fetched

def main():
    print("=" * 70)
    print("AstroScanr: Authorship Patterns in Astronomical Literature")
    print("=" * 70)
    
    # Initialize database
    db = AstroScanrDB(DB_FILE)
    db.init_schema()
    
    # Parse command-line arguments
    current_year_only = '--current-year-only' in sys.argv
    full_history = '--full-history' in sys.argv
    
    journals_to_fetch = JOURNALS
    years_to_fetch = ALL_YEARS
    
    if current_year_only:
        # Only fetch current year from specified journals
        years_to_fetch = [CURRENT_YEAR]
        # Get journals from args if provided
        remaining_args = [arg for arg in sys.argv[1:] if not arg.startswith('--')]
        if remaining_args:
            journals_to_fetch = remaining_args
    
    # Determine what to fetch
    checkpoint = db.get_checkpoint()
    if checkpoint and not full_history:
        print(f"Resuming from checkpoint...")
        journals_to_fetch = JOURNALS[checkpoint['next_journal_idx']:]
        start_idx = checkpoint['next_journal_idx']
    else:
        start_idx = 0
    
    print(f"\nFetching {len(journals_to_fetch)} journals, {len(years_to_fetch)} years...")
    print(f"Journals: {', '.join(journals_to_fetch[:3])} ... (and {len(journals_to_fetch)-3} more)")
    print()
    
    # Fetch papers
    print("Fetching papers from NASA ADS...")
    papers_count = fetch_incremental(db, journals_to_fetch, years_to_fetch)
    print(f"✅ Fetched and inserted {papers_count} papers")
    
    # Compute yearly statistics
    print("\nComputing yearly statistics...", end=" ", flush=True)
    db.compute_and_insert_yearly_stats(None)
    print(f"Done ({len(db.get_yearly_stats())} years)", flush=True)
    
    # Save checkpoint
    completed_journals = JOURNALS[:start_idx + len(journals_to_fetch)]
    db.save_checkpoint(len(JOURNALS), completed_journals, 0)
    
    # Generate plots
    print("\nGenerating plots...", flush=True)
    stats = db.get_yearly_stats()
    stats_df = pd.DataFrame(stats)
    
    # Convert to dict for plotting functions
    stats_dict = {col: stats_df[col].tolist() for col in stats_df.columns}
    
    plot_average_authors(stats_dict)
    plot_avg_and_max_authors_log(stats_dict)
    plot_author_distribution(stats_dict)
    plot_single_author_decline(stats_dict)
    plot_citation_pct_single_author(stats_dict)
    plot_people_vs_papers_ratio(stats_dict)
    
    # Export CSV for dashboard
    print("\nExporting CSV...", flush=True)
    os.system("python3 export_csv.py --output docs/astroscanr-stats.csv")
    
    print("\n" + "=" * 70)
    print("✅ Complete!")
    print("=" * 70)

# ============================================================================
# Plotting functions (copied from original)
# ============================================================================

def plot_average_authors(stats, output_dir="."):
    """Plot 1: Average authors per paper over time."""
    # Guard against empty data
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 01-avg-authors.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(stats["year"], stats["avg_authors"], linewidth=2.5, color="steelblue")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title(f"Collaboration Trend: Average Authors per Paper (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/01-avg-authors.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 01-avg-authors.png")

def plot_avg_and_max_authors_log(stats, output_dir="."):
    """Plot 2: Avg and max authors on log scale."""
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 02-avg-max-authors.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.semilogy(stats["year"], stats["avg_authors"], label="Average", linewidth=2.5, color="steelblue", marker='o', markersize=3)
    ax.semilogy(stats["year"], stats["max_authors"], label="Maximum", linewidth=2.5, color="coral", marker='s', markersize=3, alpha=0.7)
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Authors (log scale)", fontsize=12)
    ax.set_title(f"Extremes: Average vs. Maximum Authors (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/02-avg-max-authors.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 02-avg-max-authors.png")

def plot_author_distribution(stats, output_dir="."):
    """Plot 3: Distribution of single/multi-author papers."""
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 03-author-dist.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.stackplot(
        stats["year"],
        stats["pct_1author"],
        stats["pct_2author"],
        stats["pct_3author"],
        stats["pct_4author"],
        stats["pct_5plus"],
        labels=["1 author", "2 authors", "3 authors", "4 authors", "5+ authors"],
        alpha=0.8
    )
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Percentage", fontsize=12)
    ax.set_title(f"Author Distribution: Solo vs. Collaborative (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10)
    ax.set_ylim(0, 100)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/03-author-dist.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 03-author-dist.png")

def plot_single_author_decline(stats, output_dir="."):
    """Plot 4: Decline of single-author papers."""
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 04-single-author.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(stats["year"], stats["pct_1author"], width=0.8, color="steelblue", alpha=0.7)
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5, label="1960 pivot")
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Single-Author Papers (%)", fontsize=12)
    ax.set_title(f"The Solo Researcher Decline (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{output_dir}/04-single-author.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 04-single-author.png")

def plot_citation_pct_single_author(stats, output_dir="."):
    """Plot 5: Citation percentage of single-author papers."""
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 05-citations.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(stats["year"], stats["citation_pct_1author"], linewidth=2.5, color="coral", marker='o', markersize=4)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Citation % of Single-Author Papers", fontsize=12)
    ax.set_title(f"Citation Impact: Single-Author Papers (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/05-citations.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 05-citations.png")

def plot_people_vs_papers_ratio(stats, output_dir="."):
    """Plot 6: Unique authors per paper ratio."""
    if not stats.get("year") or len(stats["year"]) == 0:
        print("⚠️ Skipped: 06-ratio.png (no data)")
        return
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ratio = [a / p if p > 0 else 0 for a, p in zip(stats["num_unique_authors"], stats["num_papers"])]
    ax.plot(stats["year"], ratio, linewidth=2.5, color="darkgreen", marker='o', markersize=4)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Unique Authors per Paper", fontsize=12)
    ax.set_title(f"Collaborator Pool Growth (1827–{CURRENT_YEAR})", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/06-ratio.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 06-ratio.png")

if __name__ == "__main__":
    main()
