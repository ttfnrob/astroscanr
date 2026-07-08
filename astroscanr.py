#!/usr/bin/env python3
"""
AstroScanr: Authorship Patterns in Astronomical Literature

This script fetches data from the NASA ADS API for the main astronomy journals
(MNRAS, ApJ, A&A, etc.) and generates plots showing how authorship has evolved.

Features:
- Historical caching: stores fetched papers in JSON, reuses on subsequent runs
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
matplotlib.rcParams['figure.max_open_warning'] = 0  # Suppress warnings
import matplotlib.pyplot as plt
plt.ioff()  # Turn off interactive mode
import numpy as np
from collections import defaultdict
import pandas as pd
import sys
import os
import datetime
import time

# NASA ADS API endpoint
ADS_API_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_API_KEY = os.environ.get("ADS_API_KEY", "")

# Astronomy journals: ordered by founding year (oldest first)
# MNRAS (1831), AJ (1849), AN (1821)*, ApJ (1895), PASP (1889), Icarus (1962), 
# A&A (1969), SolPh (1967), ApJL (1969), PASA (1983), MNRASLetters (1988), NatAs (2017), OJA (2018)
# *AN founded earlier but less historical data
JOURNALS = ["AN", "MNRAS", "AJ", "ApJ", "PASP", "Icarus", "SolPh", "A&A", "ApJL", "PASA", "MNRASLetters", "NatAs", "OJA"]

# Fetch ALL years, not sampled — cache everything, analyze once
# Updated dynamically based on current year
CURRENT_YEAR = datetime.datetime.now().year
ALL_YEARS = list(range(1827, CURRENT_YEAR + 1))  # Every single year: 1827-2026 (200 years)

# Cache and checkpoint files
CACHE_FILE = "data/historical_papers.json"
CHECKPOINT_FILE = "data/fetch_checkpoint.json"

MIN_REQUEST_INTERVAL = 1.0  # seconds between API calls
RATE_LIMIT_THRESHOLD = 4500  # stop at 4500 requests to leave buffer before 5000 limit

def load_cache(cache_file=CACHE_FILE):
    """Load cached historical papers."""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache, cache_file=CACHE_FILE):
    """Save cache to disk with error handling."""
    try:
        os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)
        # Write to temp file first, then rename (atomic)
        temp_file = cache_file + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(cache, f, indent=2)
        # Atomic rename
        os.replace(temp_file, cache_file)
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}", file=sys.stderr, flush=True)
        # Try to save to a backup location
        try:
            backup_file = cache_file + ".backup"
            with open(backup_file, 'w') as f:
                json.dump(cache, f, indent=2)
            print(f"⚠️ Backup saved to {backup_file}", file=sys.stderr, flush=True)
        except:
            pass

def load_checkpoint(checkpoint_file=CHECKPOINT_FILE):
    """Load fetch progress checkpoint."""
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                return json.load(f)
        except:
            return None
    return None

def save_checkpoint(checkpoint, checkpoint_file=CHECKPOINT_FILE):
    """Save checkpoint to disk with error handling."""
    try:
        os.makedirs(os.path.dirname(checkpoint_file) or ".", exist_ok=True)
        # Write to temp file first, then rename (atomic)
        temp_file = checkpoint_file + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        # Atomic rename
        os.replace(temp_file, checkpoint_file)
        print(f"✅ Checkpoint saved: next journal #{checkpoint.get('next_journal_idx')}", flush=True)
    except Exception as e:
        print(f"⚠️ Error saving checkpoint: {e}", file=sys.stderr, flush=True)
        # Don't fail the whole script, but log it

def get_missing_journals_and_years(cache):
    """Determine which journals and years are missing from cache."""
    missing = {}
    for journal in JOURNALS:
        missing[journal] = []
        for year in ALL_YEARS:
            year_str = str(year)
            if year_str not in cache or journal not in cache[year_str]:
                missing[journal].append(year)
    return missing

def fetch_papers_by_year(journal, year, rows=200, start=0, max_retries=3):
    """Fetch papers from a journal in a given year using ADS API."""
    if not ADS_API_KEY:
        raise ValueError("ADS_API_KEY environment variable not set.")
    
    query = f'bibstem:"{journal}" year:{year}'
    params = {
        "q": query,
        "rows": rows,
        "start": start,
        "fl": "bibcode,author,year,citation_count,keyword,abstract,aff,pubdate",
    }
    
    headers = {
        "Authorization": f"Bearer {ADS_API_KEY}",
    }
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(ADS_API_URL, params=params, headers=headers, timeout=20)
            
            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', 60 * (2 ** attempt)))
                # Don't sleep longer than 5 minutes; instead skip this year/journal
                if retry_after > 300:
                    print(f"  ⏸ Rate limited (wait {retry_after}s). Skipping rest of this journal.", file=sys.stderr, flush=True)
                    return [], 0  # Return empty to signal we should move to next journal
                print(f"  ⏸ Rate limited. Waiting {retry_after}s...", file=sys.stderr, flush=True)
                time.sleep(retry_after)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", {}).get("docs", []), data.get("response", {}).get("numFound", 0)
        
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⏸ Timeout. Waiting {wait}s before retry...", file=sys.stderr, flush=True)
                time.sleep(wait)
            else:
                print(f"  ✗ Timeout after {max_retries} attempts: {journal} {year}", file=sys.stderr)
                return [], 0
        
        except Exception as e:
            print(f"  ✗ Error fetching {journal} {year}: {e}", file=sys.stderr)
            return [], 0
    
    return [], 0

def fetch_incremental(journal, years_to_fetch, cache, request_count):
    """Fetch all years for a single journal, stopping at rate limit."""
    print(f"\n📚 Fetching {journal}...")
    new_papers = {}
    last_request_time = 0
    
    for year in years_to_fetch:
        if request_count[0] >= RATE_LIMIT_THRESHOLD:
            print(f"⏹ Rate limit threshold reached ({request_count[0]}/5000 requests)")
            return new_papers, True  # Stopped due to limit
        
        # Enforce minimum time between requests
        elapsed = time.time() - last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        
        all_papers = []
        start = 0
        year_total = 0
        
        while True:
            if request_count[0] >= RATE_LIMIT_THRESHOLD:
                break
            
            papers, total = fetch_papers_by_year(journal, year, rows=200, start=start)
            request_count[0] += 1
            last_request_time = time.time()
            
            if not papers:
                break
            
            all_papers.extend(papers)
            start += len(papers)
            if start >= total:
                break
        
        # Process and cache papers
        for paper in all_papers:
            authors = paper.get("author", [])
            num_authors = len(authors) if authors else 0
            citations = paper.get("citation_count", 0) or 0
            
            if num_authors > 0:
                if year not in new_papers:
                    new_papers[year] = []
                new_papers[year].append({
                    "bibcode": paper.get("bibcode"),
                    "authors": authors,
                    "num_authors": num_authors,
                    "citations": citations,
                })
                year_total += 1
        
        print(f"  {year}: {year_total} papers (requests: {request_count[0]}/5000)")
    
    return new_papers, request_count[0] >= RATE_LIMIT_THRESHOLD

def build_dataset_from_cache(cache, current_year_only=False, use_all_journals=True):
    """Build analysis dataset from cached papers."""
    dataset = defaultdict(lambda: {
        "papers": [],
        "author_counts": [],
        "author_names": set(),
        "total_citations": 0,
    })
    
    for year_str, journal_data in cache.items():
        try:
            year = int(year_str)
            
            # Skip old years if current_year_only
            if current_year_only and year != CURRENT_YEAR:
                continue
            
            for journal, papers in journal_data.items():
                for paper in papers:
                    num_authors = paper.get("num_authors", 0)
                    if num_authors > 0:
                        dataset[year]["papers"].append(paper)
                        dataset[year]["author_counts"].append(num_authors)
                        dataset[year]["author_names"].update(paper.get("authors", []))
                        dataset[year]["total_citations"] += paper.get("citations", 0)
        except:
            pass
    
    return dict(dataset)

def analyze_dataset(dataset):
    """Compute statistics from the dataset for plotting (aggregated + per-journal)."""
    years = sorted(dataset.keys())
    
    # Initialize aggregated stats (original columns for backward compat)
    stats = {
        "year": [],
        "avg_authors": [],
        "max_authors": [],
        "pct_1author": [],
        "pct_2author": [],
        "pct_3author": [],
        "pct_4author": [],
        "pct_5plus": [],
        "num_papers": [],
        "num_unique_authors": [],
        "citation_pct_1author": [],
    }
    
    # Add per-journal column templates
    for journal in JOURNALS:
        stats[f"avg_authors_{journal}"] = []
        stats[f"max_authors_{journal}"] = []
        stats[f"num_papers_{journal}"] = []
        stats[f"num_unique_authors_{journal}"] = []
    
    for year in years:
        data = dataset[year]
        if not data["author_counts"]:
            continue
        
        stats["year"].append(year)
        stats["avg_authors"].append(np.mean(data["author_counts"]))
        stats["max_authors"].append(max(data["author_counts"]))
        stats["num_papers"].append(len(data["author_counts"]))
        stats["num_unique_authors"].append(len(data["author_names"]))
        
        # Compute percentages
        counts = data["author_counts"]
        stats["pct_1author"].append(100 * sum(1 for c in counts if c == 1) / len(counts))
        stats["pct_2author"].append(100 * sum(1 for c in counts if c == 2) / len(counts))
        stats["pct_3author"].append(100 * sum(1 for c in counts if c == 3) / len(counts))
        stats["pct_4author"].append(100 * sum(1 for c in counts if c == 4) / len(counts))
        stats["pct_5plus"].append(100 * sum(1 for c in counts if c >= 5) / len(counts))
        
        # Citation percentage for single-author papers
        single_author_citations = sum(data["papers"][i].get("citations", 0) 
                                     for i, c in enumerate(counts) if c == 1)
        total_citations = data["total_citations"] or 1
        stats["citation_pct_1author"].append(100 * single_author_citations / total_citations)
    
    return stats

def plot_average_authors(stats, output_dir="."):
    """Plot 1: Average authors per paper over time."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(stats["year"], stats["avg_authors"], linewidth=2.5, color="steelblue")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title("Collaboration Trend: Average Authors per Paper (1827–{})", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/01-avg-authors.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    plt.close(fig)
    print("✓ Saved: 01-avg-authors.png")

def plot_avg_and_max_authors_log(stats, output_dir="."):
    """Plot 2: Average and max authors (log scale)."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.semilogy(stats["year"], stats["avg_authors"], linewidth=2.5, label="Average", color="steelblue")
    ax.semilogy(stats["year"], stats["max_authors"], linewidth=2.5, label="Maximum", color="coral", linestyle="--")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Authors (log scale)", fontsize=12)
    ax.set_title("Authorship Scaling: Average vs Maximum (Log Scale)", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, which="both")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/02-avg-max-log.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 02-avg-max-log.png")

def plot_author_distribution(stats, output_dir="."):
    """Plot 3: Author count distribution (stacked area)."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.stackplot(stats["year"], 
                 stats["pct_1author"], stats["pct_2author"], stats["pct_3author"],
                 stats["pct_4author"], stats["pct_5plus"],
                 labels=["1 author", "2 authors", "3 authors", "4 authors", "5+ authors"],
                 colors=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"])
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Percentage of Papers (%)", fontsize=12)
    ax.set_title("Who Writes Astronomy Papers?\nPercentage of papers by number of authors (1827–present)", fontsize=14, fontweight="bold")
    ax.legend(loc="center left", fontsize=10)
    ax.set_ylim([0, 100])
    plt.tight_layout()
    plt.savefig(f"{output_dir}/03-distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 03-distribution.png")

def plot_citation_weighted_distribution(stats, output_dir="."):
    """Plot 4: Citation percentage for single-author papers."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(stats["year"], stats["citation_pct_1author"], linewidth=2.5, color="darkred")
    ax.fill_between(stats["year"], stats["citation_pct_1author"], alpha=0.3, color="red")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("% of Citations from 1-Author Papers", fontsize=12)
    ax.set_title("Do Solo Papers Still Get Cited?\n% of all citations going to single-author papers (1827–present)", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/04-citation-weighted.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 04-citation-weighted.png")

def plot_population_and_papers(stats, output_dir="."):
    """Plot 5: Unique authors and papers (dual-axis)."""
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    ax1.set_xlabel("Year", fontsize=12)
    ax1.set_ylabel("Number of Papers", fontsize=12, color="steelblue")
    ax1.plot(stats["year"], stats["num_papers"], linewidth=2.5, color="steelblue", label="Papers")
    ax1.tick_params(axis="y", labelcolor="steelblue")
    
    ax2 = ax1.twinx()
    ax2.set_ylabel("Unique Authors", fontsize=12, color="coral")
    ax2.plot(stats["year"], stats["num_unique_authors"], linewidth=2.5, color="coral", linestyle="--", label="Unique Authors")
    ax2.tick_params(axis="y", labelcolor="coral")
    
    ax1.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax1.set_title("Research Growth: Papers and Unique Authors Over Time", fontsize=14, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    
    fig.tight_layout()
    plt.savefig(f"{output_dir}/05-population-papers.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 05-population-papers.png")

def plot_people_vs_papers_ratio(stats, output_dir="."):
    """Plot 6: Ratio of unique authors to papers."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ratio = np.array(stats["num_unique_authors"]) / np.array(stats["num_papers"])
    ax.plot(stats["year"], ratio, linewidth=2.5, color="steelblue")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Unique Authors per Paper", fontsize=12)
    ax.set_title("Research Efficiency: Unique Authors per Paper", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/06-ratio.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("✓ Saved: 06-ratio.png")


def fill_per_journal_stats(stats, cache):
    """Fill per-journal stats from cache into stats dict."""
    for i, year in enumerate(stats["year"]):
        year_str = str(year)
        year_data = cache.get(year_str, {})
        
        for journal in JOURNALS:
            journal_papers = year_data.get(journal, [])
            
            if journal_papers:
                author_counts = [p.get("num_authors", 0) for p in journal_papers if p.get("num_authors", 0) > 0]
                author_names = set()
                for p in journal_papers:
                    author_names.update(p.get("authors", []))
                
                if author_counts:
                    stats[f"avg_authors_{journal}"][i] = np.mean(author_counts)
                    stats[f"max_authors_{journal}"][i] = max(author_counts)
                    stats[f"num_papers_{journal}"][i] = len(author_counts)
                    stats[f"num_unique_authors_{journal}"][i] = len(author_names)
    
    return stats

def main():
    print("=" * 70)
    print("AstroScanr: Authorship Patterns in Astronomical Literature")
    print("=" * 70)
    print()
    
    if not ADS_API_KEY:
        print("ERROR: ADS_API_KEY environment variable not set.")
        sys.exit(1)
    
    # Parse command-line flags
    full_history = "--full-history" in sys.argv
    current_year_only = "--current-year-only" in sys.argv
    
    # Load cache
    cache = load_cache()
    checkpoint = load_checkpoint() if not full_history else None
    
    # Determine mode
    if current_year_only:
        print(f"📅 Mode: Current year only ({CURRENT_YEAR})")
        print(f"📦 Cache has {sum(len(y) for y in cache.values())} year entries\n")
    elif full_history:
        print("🔄 Mode: Force full historical rebuild (ignoring checkpoint)")
        checkpoint = None
    else:
        print("📈 Mode: Daily incremental (resumes from checkpoint)\n")
        missing = get_missing_journals_and_years(cache)
        total_missing = sum(len(years) for years in missing.values())
        print(f"📦 Cache: {len(cache)} years with data")
        print(f"❌ Missing: {total_missing} journal-year combinations\n")
    
    request_count = [0]
    
    # Fetch data
    if current_year_only:
        # Quick weekly run: just current year
        dataset = build_dataset_from_cache(cache, current_year_only=True)
        print(f"Loaded {len(dataset)} year(s) for analysis")
    else:
        # Incremental daily run — fetch 5 journals per day
        if checkpoint:
            next_idx = checkpoint.get("next_journal_idx", 0)
            years_done = checkpoint.get("completed_journals", [])
            print(f"▶ Resuming from journal #{next_idx}: {JOURNALS[next_idx]}\n")
        else:
            next_idx = 0
            years_done = []
        
        # Fetch up to 2 journals today (ADS is rate-limiting more aggressively than expected)
        # Tested: 3 journals hit rate limit even though requests seem under 5000
        # Going back to 2 journals/day which was working reliably
        missing = get_missing_journals_and_years(cache)
        journals_to_fetch = []
        hit_limit = False
        JOURNALS_PER_RUN = 2  # Safe: 2 journals/day, completes in ~7 days
        
        for i in range(JOURNALS_PER_RUN):  # Try to fetch 2 journals
            current_idx = (next_idx + i) % len(JOURNALS)
            journal = JOURNALS[current_idx]
            
            if request_count[0] >= RATE_LIMIT_THRESHOLD:
                print(f"⏹ Rate limit reached after {len(journals_to_fetch)} journals")
                hit_limit = True
                break
            
            years_to_fetch = missing[journal]
            
            if not years_to_fetch:
                # No missing years — but always refresh the current year
                # This keeps data fresh once the historical cache is complete
                print(f"🔄 {journal} fully cached — refreshing current year ({CURRENT_YEAR})")
                years_to_fetch = [CURRENT_YEAR]
            
            print(f"\n📚 [{i+1}/{JOURNALS_PER_RUN}] Fetching {journal} ({len(years_to_fetch)} years)...")
            new_papers, limit_hit = fetch_incremental(journal, years_to_fetch, cache, request_count)
            
            # Merge into cache
            for year, papers in new_papers.items():
                year_str = str(year)
                if year_str not in cache:
                    cache[year_str] = {}
                cache[year_str][journal] = papers
            
            save_cache(cache)
            print(f"✅ {journal} done ({len(new_papers)} years, {request_count[0]}/5000 requests)")
            journals_to_fetch.append(journal)
            years_done.append(journal)
            
            if limit_hit:
                hit_limit = True
                break
        
        # Update checkpoint for next run
        if hit_limit or request_count[0] >= RATE_LIMIT_THRESHOLD:
            next_run_idx = (next_idx + len(journals_to_fetch)) % len(JOURNALS)
            save_checkpoint({
                "next_journal_idx": next_run_idx,
                "completed_journals": years_done,
                "last_run": datetime.datetime.now().isoformat(),
                "requests_used": request_count[0],
            })
            next_journal = JOURNALS[next_run_idx]
            print(f"\n⏹ Rate limit hit. Checkpoint saved.")
            print(f"   Tomorrow: start from journal #{next_run_idx} ({next_journal})")
        else:
            # All journals fetched, no limit hit — update for next batch
            next_run_idx = (next_idx + JOURNALS_PER_RUN) % len(JOURNALS)
            save_checkpoint({
                "next_journal_idx": next_run_idx,
                "completed_journals": years_done,
                "last_run": datetime.datetime.now().isoformat(),
                "requests_used": request_count[0],
            })
            next_journal = JOURNALS[next_run_idx]
            print(f"\n✅ {len(journals_to_fetch)} journals completed today")
            print(f"   Tomorrow: continue with journal #{next_run_idx} ({next_journal})")
        
        # Build dataset from full cache for analysis
        dataset = build_dataset_from_cache(cache, current_year_only=False)
    
    # Analyze and plot with error handling
    try:
        print("\nAnalyzing...", end=" ", flush=True)
        stats = analyze_dataset(dataset)
        stats = fill_per_journal_stats(stats, cache)
        print(f"Done ({len(stats['year'])} years)", flush=True)
        
        print("\nGenerating plots...", flush=True)
        plot_average_authors(stats)
        plot_avg_and_max_authors_log(stats)
        plot_author_distribution(stats)
        plot_citation_weighted_distribution(stats)
        plot_population_and_papers(stats)
        plot_people_vs_papers_ratio(stats)
        print("✅ All plots generated", flush=True)
        
        # Save stats
        print("Saving stats...", end=" ", flush=True)
        df = pd.DataFrame(stats)
        df.to_csv("astroscanr-stats.csv", index=False)
        print("Done", flush=True)
    except Exception as e:
        print(f"\n⚠️ Error during analysis/plotting: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print("⚠️ Continuing despite analysis error (cache and checkpoint still saved)", file=sys.stderr, flush=True)
    
    print("\n" + "=" * 70)
    print("✓ Analysis complete!")
    print("=" * 70)
    print(f"  {len(stats['year'])} years analyzed")
    print(f"  {int(sum(stats['num_papers'])):,} papers")
    print(f"  {int(sum(stats['num_unique_authors'])):,} unique authors")
    print(f"  API requests used: {request_count[0]}/5000")
    print()

if __name__ == "__main__":
    main()
