#!/usr/bin/env python3
"""
AstroScanr: Authorship Patterns in Astronomical Literature

This script fetches data from the NASA ADS API for the main astronomy journals
(MNRAS, ApJ, A&A, AJ, PASP) and generates plots showing how authorship has
evolved from 1827 to 2025.

Usage:
    export ADS_API_KEY="your-token-here"
    python3 astroscanr.py
"""

import requests
import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import pandas as pd
import sys
import os

# NASA ADS API endpoint
ADS_API_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_API_KEY = os.environ.get("ADS_API_KEY", "")

# Main astronomy journals from the original analysis
JOURNALS = ["MNRAS", "ApJ", "A&A", "AJ", "PASP"]

# Sample years for faster processing: every 5 years before 1950, every 2 years after
YEARS = list(range(1827, 1950, 5)) + list(range(1950, 2026, 2))

def fetch_papers_by_year(journal, year, rows=200, start=0):
    """
    Fetch papers from a journal in a given year using ADS API.
    Returns (papers, total_count).
    """
    if not ADS_API_KEY:
        raise ValueError("ADS_API_KEY environment variable not set. Get a token from https://ui.adsabs.harvard.edu/user/settings/token")
    
    query = f'bibstem:"{journal}" year:{year}'
    params = {
        "q": query,
        "rows": rows,
        "start": start,
        "fl": "bibcode,author,year,citation_count",
    }
    
    headers = {
        "Authorization": f"Bearer {ADS_API_KEY}",
    }
    
    try:
        resp = requests.get(ADS_API_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", {}).get("docs", []), data.get("response", {}).get("numFound", 0)
    except Exception as e:
        print(f"  ⚠ Error fetching {journal} {year}: {e}", file=sys.stderr)
        return [], 0

def build_dataset(journals=JOURNALS, years=YEARS):
    """
    Fetch authorship data from ADS for selected journals and years.
    Returns a dict keyed by year with aggregated stats.
    """
    dataset = defaultdict(lambda: {
        "papers": [],
        "author_counts": [],
        "author_names": set(),
        "total_citations": 0,
    })
    
    total_years = len(years)
    print(f"Fetching data from {len(journals)} journals across {total_years} sampled years...")
    print(f"(1827-1950: 5-year samples; 1950-2025: 2-year samples)\n")
    
    for i, year in enumerate(years):
        print(f"[{i+1:2d}/{total_years}] Year {year}...", end=" ", flush=True)
        year_papers = 0
        
        for journal in journals:
            # Fetch all papers for this journal/year
            all_papers = []
            total = 0
            start = 0
            
            while True:
                papers, total = fetch_papers_by_year(journal, year, rows=200, start=start)
                if not papers:
                    break
                all_papers.extend(papers)
                start += len(papers)
                if start >= total:
                    break
            
            # Process papers
            for paper in all_papers:
                authors = paper.get("author", [])
                num_authors = len(authors) if authors else 0
                citations = paper.get("citation_count", 0) or 0
                
                if num_authors > 0:
                    dataset[year]["papers"].append({
                        "bibcode": paper.get("bibcode"),
                        "authors": authors,
                        "num_authors": num_authors,
                        "citations": citations,
                    })
                    dataset[year]["author_counts"].append(num_authors)
                    dataset[year]["author_names"].update(authors)
                    dataset[year]["total_citations"] += citations
                    year_papers += 1
        
        print(f"{year_papers:5d} papers")
    
    return dict(dataset)

def analyze_dataset(dataset):
    """
    Compute statistics from the dataset for plotting.
    """
    years = sorted(dataset.keys())
    
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
        "citation_pct_2author": [],
        "citation_pct_3author": [],
        "citation_pct_4author": [],
        "citation_pct_5plus": [],
    }
    
    for year in years:
        data = dataset[year]
        author_counts = data["author_counts"]
        papers = data["papers"]
        
        if not papers:
            continue
        
        stats["year"].append(year)
        stats["num_papers"].append(len(papers))
        stats["num_unique_authors"].append(len(data["author_names"]))
        stats["avg_authors"].append(np.mean(author_counts))
        stats["max_authors"].append(np.max(author_counts))
        
        # Distribution by author count
        total_papers = len(papers)
        pct_1 = sum(1 for c in author_counts if c == 1) / total_papers * 100
        pct_2 = sum(1 for c in author_counts if c == 2) / total_papers * 100
        pct_3 = sum(1 for c in author_counts if c == 3) / total_papers * 100
        pct_4 = sum(1 for c in author_counts if c == 4) / total_papers * 100
        pct_5plus = sum(1 for c in author_counts if c >= 5) / total_papers * 100
        
        stats["pct_1author"].append(pct_1)
        stats["pct_2author"].append(pct_2)
        stats["pct_3author"].append(pct_3)
        stats["pct_4author"].append(pct_4)
        stats["pct_5plus"].append(pct_5plus)
        
        # Citation-weighted distribution
        total_citations = sum(p["citations"] for p in papers)
        if total_citations > 0:
            cit_1 = sum(p["citations"] for p in papers if p["num_authors"] == 1) / total_citations * 100
            cit_2 = sum(p["citations"] for p in papers if p["num_authors"] == 2) / total_citations * 100
            cit_3 = sum(p["citations"] for p in papers if p["num_authors"] == 3) / total_citations * 100
            cit_4 = sum(p["citations"] for p in papers if p["num_authors"] == 4) / total_citations * 100
            cit_5plus = sum(p["citations"] for p in papers if p["num_authors"] >= 5) / total_citations * 100
        else:
            cit_1 = cit_2 = cit_3 = cit_4 = cit_5plus = 0
        
        stats["citation_pct_1author"].append(cit_1)
        stats["citation_pct_2author"].append(cit_2)
        stats["citation_pct_3author"].append(cit_3)
        stats["citation_pct_4author"].append(cit_4)
        stats["citation_pct_5plus"].append(cit_5plus)
    
    return stats

def plot_average_authors(stats, output_dir="."):
    """Plot 1: Average authors per paper over time."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(stats["year"], stats["avg_authors"], linewidth=2.5, color="steelblue")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5, label="1960 (inflection point)")
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title("Authorship in Astronomy: Average Authors per Paper (1827–2025)", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{output_dir}/01-avg-authors.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 01-avg-authors.png")

def plot_avg_and_max_authors_log(stats, output_dir="."):
    """Plot 2: Average and max authors on log scale."""
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.semilogy(stats["year"], stats["avg_authors"], linewidth=2.5, label="Average", color="steelblue")
    ax.semilogy(stats["year"], stats["max_authors"], linewidth=2.5, label="Maximum", color="coral")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Number of Authors (log scale)", fontsize=12)
    ax.set_title("Authorship in Astronomy: Average and Maximum Authors (Log Scale)", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, which="both")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/02-avg-max-log.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 02-avg-max-log.png")

def plot_author_distribution(stats, output_dir="."):
    """Plot 3: Percentage of papers by author count."""
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.stackplot(
        stats["year"],
        stats["pct_1author"],
        stats["pct_2author"],
        stats["pct_3author"],
        stats["pct_4author"],
        stats["pct_5plus"],
        labels=["1 author", "2 authors", "3 authors", "4 authors", "5+ authors"],
        colors=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],
        alpha=0.85,
    )
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Percentage of Papers (%)", fontsize=12)
    ax.set_title("Authorship Distribution in Astronomy (1827–2025)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=11)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/03-distribution.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 03-distribution.png")

def plot_citation_weighted_distribution(stats, output_dir="."):
    """Plot 4: Citation-weighted distribution."""
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.stackplot(
        stats["year"],
        stats["citation_pct_1author"],
        stats["citation_pct_2author"],
        stats["citation_pct_3author"],
        stats["citation_pct_4author"],
        stats["citation_pct_5plus"],
        labels=["1 author", "2 authors", "3 authors", "4 authors", "5+ authors"],
        colors=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],
        alpha=0.85,
    )
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Percentage of Citations (%)", fontsize=12)
    ax.set_title("Citation-Weighted Authorship Distribution in Astronomy (1827–2025)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=11)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/04-citation-weighted.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 04-citation-weighted.png")

def plot_population_and_papers(stats, output_dir="."):
    """Plot 5 & 6: Research population and number of papers."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Population
    ax1.plot(stats["year"], stats["num_unique_authors"], linewidth=2.5, color="steelblue")
    ax1.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax1.set_ylabel("Unique Authors (de-duplicated names)", fontsize=12)
    ax1.set_title("Research Population in Astronomy (1827–2025)", fontsize=14, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    
    # Papers per year
    ax2.plot(stats["year"], stats["num_papers"], linewidth=2.5, color="coral")
    ax2.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax2.set_xlabel("Year", fontsize=12)
    ax2.set_ylabel("Number of Papers", fontsize=12)
    ax2.set_title("Papers Published per Year (1827–2025)", fontsize=14, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(f"{output_dir}/05-population-papers.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 05-population-papers.png")

def plot_people_vs_papers_ratio(stats, output_dir="."):
    """Plot 6: Ratio of unique authors to papers per year."""
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Compute rolling ratio: people / papers
    ratio = np.array(stats["num_unique_authors"]) / np.array(stats["num_papers"])
    
    ax.plot(stats["year"], ratio, linewidth=2.5, color="steelblue")
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Unique Authors per Paper", fontsize=12)
    ax.set_title("Research Efficiency: Unique Authors per Paper (1827–2025)", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/06-ratio.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 06-ratio.png")

def main():
    print("=" * 70)
    print("AstroScanr: Authorship Patterns in Astronomical Literature")
    print("=" * 70)
    print()
    
    # Check for API key
    if not ADS_API_KEY:
        print("ERROR: ADS_API_KEY environment variable not set.")
        print("Get your token from: https://ui.adsabs.harvard.edu/user/settings/token")
        print("\nThen run:")
        print("  export ADS_API_KEY='your-token-here'")
        print("  python3 astroscanr.py")
        sys.exit(1)
    
    # Fetch data
    dataset = build_dataset()
    
    # Analyze
    print("\nAnalyzing...", end=" ", flush=True)
    stats = analyze_dataset(dataset)
    print(f"Done ({len(stats['year'])} years)")
    
    # Create plots
    print("\nGenerating plots...")
    plot_average_authors(stats)
    plot_avg_and_max_authors_log(stats)
    plot_author_distribution(stats)
    plot_citation_weighted_distribution(stats)
    plot_population_and_papers(stats)
    plot_people_vs_papers_ratio(stats)
    
    # Save stats to CSV for reference
    print("\nSaving stats...", end=" ", flush=True)
    df = pd.DataFrame(stats)
    df.to_csv("astroscanr-stats.csv", index=False)
    print("Done")
    
    print("\n" + "=" * 70)
    print("✓ Analysis complete!")
    print("=" * 70)
    print(f"  {len(stats['year'])} years of data")
    print(f"  {int(sum(stats['num_papers'])):,} papers analysed")
    print(f"  {int(sum(stats['num_unique_authors'])):,} unique authors")
    print(f"\nFiles:")
    print("  - astroscanr-stats.csv (raw data)")
    print("  - 01-avg-authors.png")
    print("  - 02-avg-max-log.png")
    print("  - 03-distribution.png")
    print("  - 04-citation-weighted.png")
    print("  - 05-population-papers.png")
    print("  - 06-ratio.png")
    print()

if __name__ == "__main__":
    main()
