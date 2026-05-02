#!/usr/bin/env python3
"""
AstroScanr Extended: Field-specific, citation velocity, affiliations, author career arcs.

Extends the base analysis with deeper insights into collaboration patterns.
"""

import requests
import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict, Counter
import pandas as pd
import sys
import os
from datetime import datetime

# NASA ADS API endpoint
ADS_API_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_API_KEY = os.environ.get("ADS_API_KEY", "")

JOURNALS = ["MNRAS", "ApJ", "A&A", "AJ", "PASP", "NatAs", "ApJL", "PASA", "MNRASLetters", "AN", "Icarus", "SolPh", "OJA"]
YEARS = list(range(1827, 1950, 5)) + list(range(1950, 2026, 2))

def fetch_papers_by_year_extended(journal, year, rows=200, start=0, max_retries=3):
    """
    Fetch papers with extended fields: keywords, abstract, affiliations, pubdate.
    """
    if not ADS_API_KEY:
        raise ValueError("ADS_API_KEY not set")
    
    query = f'bibstem:"{journal}" year:{year}'
    params = {
        "q": query,
        "rows": rows,
        "start": start,
        "fl": "bibcode,author,year,citation_count,keyword,abstract,aff,pubdate",
    }
    
    headers = {"Authorization": f"Bearer {ADS_API_KEY}"}
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(ADS_API_URL, params=params, headers=headers, timeout=20)
            
            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', 60 * (2 ** attempt)))
                print(f"  Rate limited. Waiting {retry_after}s...", file=sys.stderr, flush=True)
                import time
                time.sleep(retry_after)
                continue
            
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", {}).get("docs", []), data.get("response", {}).get("numFound", 0)
        
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"  Timeout. Waiting {wait}s...", file=sys.stderr, flush=True)
                import time
                time.sleep(wait)
            else:
                return [], 0
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            return [], 0
    
    return [], 0

def build_dataset_extended():
    """Build dataset with all extended fields."""
    dataset = defaultdict(lambda: {
        "papers": [],
        "author_counts": [],
        "author_names": set(),
        "keywords": defaultdict(int),
        "affiliations": [],
        "author_papers": defaultdict(list),  # author -> [(year, num_authors), ...]
        "citation_times": [],
    })
    
    total_years = len(YEARS)
    print(f"Fetching extended data: {len(JOURNALS)} journals, {total_years} years...")
    print(f"Journals: {', '.join(JOURNALS)}\n")
    
    import time
    last_request_time = 0
    MIN_REQUEST_INTERVAL = 0.5
    
    for i, year in enumerate(YEARS):
        print(f"[{i+1:2d}/{total_years}] {year}...", end=" ", flush=True)
        year_papers = 0
        
        for journal in JOURNALS:
            all_papers = []
            total = 0
            start = 0
            
            while True:
                elapsed = time.time() - last_request_time
                if elapsed < MIN_REQUEST_INTERVAL:
                    time.sleep(MIN_REQUEST_INTERVAL - elapsed)
                
                papers, total = fetch_papers_by_year_extended(journal, year, rows=200, start=start)
                last_request_time = time.time()
                
                if not papers:
                    break
                all_papers.extend(papers)
                start += len(papers)
                if start >= total:
                    break
            
            for paper in all_papers:
                authors = paper.get("author", [])
                num_authors = len(authors) if authors else 0
                citations = paper.get("citation_count", 0) or 0
                keywords = paper.get("keyword", []) or []
                affiliations = paper.get("aff", []) or []
                
                if num_authors > 0:
                    dataset[year]["papers"].append({
                        "bibcode": paper.get("bibcode"),
                        "authors": authors,
                        "num_authors": num_authors,
                        "citations": citations,
                        "keywords": keywords,
                        "affiliations": affiliations,
                    })
                    dataset[year]["author_counts"].append(num_authors)
                    dataset[year]["author_names"].update(authors)
                    
                    # Track each author
                    for author in authors:
                        dataset[year]["author_papers"][author].append((year, num_authors))
                    
                    # Keywords
                    for kw in keywords:
                        dataset[year]["keywords"][kw] += 1
                    
                    # Affiliations
                    dataset[year]["affiliations"].extend(affiliations)
                    
                    year_papers += 1
        
        print(f"{year_papers:5d} papers")
    
    return dict(dataset)

def classify_field(keywords):
    """Classify paper by keywords into astronomy subfields."""
    keywords_str = " ".join(keywords).lower()
    
    if any(w in keywords_str for w in ["exoplanet", "planet", "transit", "radial velocity"]):
        return "Exoplanets"
    elif any(w in keywords_str for w in ["survey", "sdss", "photometry", "spectroscopy", "catalog"]):
        return "Surveys/Photometry"
    elif any(w in keywords_str for w in ["cosmology", "dark matter", "dark energy", "redshift", "cmb"]):
        return "Cosmology"
    elif any(w in keywords_str for w in ["stellar", "star", "evolution", "asteroseismology"]):
        return "Stellar Physics"
    elif any(w in keywords_str for w in ["galaxy", "galaxies", "morphology", "bulge", "disk"]):
        return "Galaxies"
    elif any(w in keywords_str for w in ["black hole", "neutron star", "compact", "accretion"]):
        return "Compact Objects"
    elif any(w in keywords_str for w in ["formation", "star formation", "protostar", "cloud", "dust"]):
        return "Star Formation"
    else:
        return "Other"

def classify_institution(affiliations):
    """Classify institution by affiliation string."""
    aff_str = " ".join(affiliations).lower()
    
    # Simple heuristic: check for country markers
    if any(c in aff_str for c in ["usa", "united states", "us", "america"]):
        return "USA"
    elif any(c in aff_str for c in ["uk", "england", "scotland", "britain", "brit"]):
        return "UK"
    elif any(c in aff_str for c in ["france", "paris", "lyon"]):
        return "France"
    elif any(c in aff_str for c in ["germany", "deutschland", "munich", "berlin"]):
        return "Germany"
    elif any(c in aff_str for c in ["italy", "italia", "rome", "milan"]):
        return "Italy"
    elif any(c in aff_str for c in ["europe", "esа", "eso"]):
        return "Europe"
    elif any(c in aff_str for c in ["china", "china", "beijing", "shanghai"]):
        return "China"
    elif any(c in aff_str for c in ["japan", "tokyo", "osaka"]):
        return "Japan"
    elif any(c in aff_str for c in ["india", "indian", "delhi", "bangalore"]):
        return "India"
    elif any(c in aff_str for c in ["australia", "sydney", "melbourne"]):
        return "Australia"
    elif any(c in aff_str for c in ["canada", "toronto", "vancouver"]):
        return "Canada"
    else:
        return "Other"

def estimate_seniority(author_history):
    """
    Estimate author seniority based on publication span.
    Long spans suggest senior researchers.
    """
    if not author_history:
        return "Unknown"
    years = sorted([year for year, _ in author_history])
    span = years[-1] - years[0]
    
    if span < 3:
        return "Early-Career"
    elif span < 10:
        return "Mid-Career"
    else:
        return "Senior"

def analyze_fields(dataset):
    """Analyze co-authorship trends by field."""
    field_stats = defaultdict(lambda: {
        "years": [],
        "avg_authors": [],
        "paper_count": [],
    })
    
    for year in sorted(dataset.keys()):
        papers = dataset[year]["papers"]
        
        # Classify each paper
        field_counts = defaultdict(list)
        for paper in papers:
            field = classify_field(paper["keywords"])
            field_counts[field].append(paper["num_authors"])
        
        # Aggregate by field
        for field, author_counts in field_counts.items():
            field_stats[field]["years"].append(year)
            field_stats[field]["avg_authors"].append(np.mean(author_counts))
            field_stats[field]["paper_count"].append(len(author_counts))
    
    return field_stats

def analyze_affiliations(dataset):
    """Analyze co-authorship by institution region."""
    region_stats = defaultdict(lambda: {
        "years": [],
        "avg_authors": [],
        "paper_count": [],
    })
    
    for year in sorted(dataset.keys()):
        papers = dataset[year]["papers"]
        
        region_counts = defaultdict(list)
        for paper in papers:
            # Classify the paper by its affiliations
            region = classify_institution(paper["affiliations"])
            region_counts[region].append(paper["num_authors"])
        
        for region, author_counts in region_counts.items():
            region_stats[region]["years"].append(year)
            region_stats[region]["avg_authors"].append(np.mean(author_counts))
            region_stats[region]["paper_count"].append(len(author_counts))
    
    return region_stats

def analyze_author_careers(dataset):
    """Analyze co-authorship by estimated author seniority."""
    seniority_stats = defaultdict(lambda: {
        "years": [],
        "avg_authors": [],
        "author_count": [],
    })
    
    # Build global author history
    all_author_history = defaultdict(list)
    for year in sorted(dataset.keys()):
        for author, papers in dataset[year]["author_papers"].items():
            for py, num_auth in papers:
                all_author_history[author].append((py, num_auth))
    
    # Now classify papers by author seniority
    for year in sorted(dataset.keys()):
        papers = dataset[year]["papers"]
        
        seniority_counts = defaultdict(list)
        for paper in papers:
            # Estimate seniority of paper based on its authors
            author_seniorities = [estimate_seniority(all_author_history[a]) for a in paper["authors"]]
            # Take the mode (most common) or the senior-most
            if "Senior" in author_seniorities:
                paper_seniority = "Senior"
            elif "Mid-Career" in author_seniorities:
                paper_seniority = "Mid-Career"
            else:
                paper_seniority = "Early-Career"
            
            seniority_counts[paper_seniority].append(paper["num_authors"])
        
        for seniority, author_counts in seniority_counts.items():
            seniority_stats[seniority]["years"].append(year)
            seniority_stats[seniority]["avg_authors"].append(np.mean(author_counts))
            seniority_stats[seniority]["author_count"].append(len(author_counts))
    
    return seniority_stats

def plot_fields(field_stats, output_dir="."):
    """Plot co-authorship trends by field."""
    fig, ax = plt.subplots(figsize=(14, 7))
    
    colors = plt.cm.Set3(np.linspace(0, 1, len(field_stats)))
    
    for (field, stats), color in zip(sorted(field_stats.items()), colors):
        if len(stats["years"]) > 2:  # Only plot fields with decent data
            ax.plot(stats["years"], stats["avg_authors"], label=field, linewidth=2, color=color, marker='o', markersize=4)
    
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title("Co-authorship Trends by Astronomy Subfield (1827-2024)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10, ncol=2)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/07-fields.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 07-fields.png")

def plot_citation_velocity(dataset, output_dir="."):
    """
    Plot citation growth rate: how quickly papers accumulate citations by publication year.
    Proxy for citation velocity.
    """
    years = sorted(dataset.keys())
    avg_citations = []
    
    for year in years:
        papers = dataset[year]["papers"]
        citations = [p["citations"] for p in papers]
        if citations:
            avg_citations.append(np.mean(citations))
        else:
            avg_citations.append(0)
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(years, avg_citations, linewidth=2.5, color="steelblue", marker='o', markersize=5)
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Citations per Paper", fontsize=12)
    ax.set_title("Citation Accumulation: Average Citations by Publication Year (1827-2024)", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/08-citation-velocity.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 08-citation-velocity.png")

def plot_affiliations(region_stats, output_dir="."):
    """Plot co-authorship by institution region."""
    fig, ax = plt.subplots(figsize=(14, 7))
    
    colors = plt.cm.Set2(np.linspace(0, 1, len(region_stats)))
    
    for (region, stats), color in zip(sorted(region_stats.items()), colors):
        if len(stats["years"]) > 2:
            ax.plot(stats["years"], stats["avg_authors"], label=region, linewidth=2, color=color, marker='s', markersize=4)
    
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title("Co-authorship by Institution Region (1827-2024)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=10, ncol=2)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/09-affiliations.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 09-affiliations.png")

def plot_seniority(seniority_stats, output_dir="."):
    """Plot co-authorship by author seniority."""
    fig, ax = plt.subplots(figsize=(12, 7))
    
    colors_map = {
        "Early-Career": "#1f77b4",
        "Mid-Career": "#ff7f0e",
        "Senior": "#2ca02c",
        "Unknown": "#d62728",
    }
    
    for seniority in ["Early-Career", "Mid-Career", "Senior"]:
        if seniority in seniority_stats:
            stats = seniority_stats[seniority]
            if len(stats["years"]) > 2:
                ax.plot(stats["years"], stats["avg_authors"], label=seniority, linewidth=2.5, 
                       color=colors_map.get(seniority, "#999"), marker='D', markersize=5)
    
    ax.axvline(x=1960, color="gray", linestyle="--", alpha=0.5)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average Authors per Paper", fontsize=12)
    ax.set_title("Co-authorship by Author Seniority (1827-2024)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/10-seniority.png", dpi=150, bbox_inches="tight")
    print("✓ Saved: 10-seniority.png")

def main():
    print("=" * 70)
    print("AstroScanr Extended Analysis")
    print("=" * 70)
    print()
    
    if not ADS_API_KEY:
        print("ERROR: ADS_API_KEY not set")
        sys.exit(1)
    
    # Build extended dataset
    dataset = build_dataset_extended()
    
    print("\nAnalyzing...")
    field_stats = analyze_fields(dataset)
    region_stats = analyze_affiliations(dataset)
    seniority_stats = analyze_author_careers(dataset)
    
    # Generate plots
    print("\nGenerating plots...")
    plot_fields(field_stats)
    plot_citation_velocity(dataset)
    plot_affiliations(region_stats)
    plot_seniority(seniority_stats)
    
    print("\n" + "=" * 70)
    print("Extended analysis complete")
    print("=" * 70)

if __name__ == "__main__":
    main()
