# AstroScanr: Authorship Patterns in Astronomical Literature

A data mining analysis of authorship trends across 200 years of astronomical literature (1827–2025), using the NASA ADS API.

**Live demo:** https://ttfnrob.github.io/astroscanr/

## Overview

This project resurrects and extends the 2012 analysis by Rob Simpson, examining how authorship has evolved in astronomy from single-author papers in the 19th century to large collaborations in the modern era (LIGO, JWST, LSST, EHT).

### Key Questions

- How has the average number of co-authors changed over time?
- When did single-author papers become the minority?
- How do citation patterns favour different authorship models?
- How has the research population grown relative to paper output?

## Original Findings (2012)

- **1827–1960:** Authorship remained flat, averaging ~1 author per paper
- **1960+:** Sharp acceleration in co-authorship; by 2012:
  - Single-author papers: 6% (down from ~100% in 1827)
  - Papers with 5+ authors: largest category
  - Largest paper: 770 co-authors (LIGO gravitational wave search, 2011)
- **Research population:** Grew faster than paper output from 1960 onward

## Usage

### Requirements

- Python 3.8+
- `requests`, `matplotlib`, `pandas`, `numpy`
- NASA ADS API token (free, from https://ui.adsabs.harvard.edu/user/settings/token)

### Running the Analysis

```bash
# Clone and install
git clone https://github.com/ttfnrob/astroscanr
cd astroscanr
pip install -r requirements.txt

# Set your ADS API key
export ADS_API_KEY="your-token-here"

# Run the analysis
python3 astroscanr.py
```

This generates:
- `astroscanr-stats.csv` — Raw statistics by year
- `*.png` — Six publication-ready plots
- `ANALYSIS.md` — Detailed findings

## Data Sources

- **NASA ADS API:** https://ui.adsabs.harvard.edu/help/api/
- **Journals:** MNRAS, ApJ, A&A, AJ, PASP (the five major refereed astronomy journals)
- **Span:** 1827–2025 (sampled at 5-year intervals pre-1950, 2-year intervals 1950+)

## Plots

1. **Average authors per paper** — Linear trend from 1 to 2025
2. **Average + Maximum authors** — Log scale showing collaboration explosion
3. **Authorship distribution** — Stacked area chart of paper percentages by author count
4. **Citation-weighted distribution** — How citations skew toward collaborative work
5. **Population & output** — Research population vs. papers per year
6. **Research efficiency** — Unique authors per paper (productivity metric)

## Findings (2025 Update)

_[To be populated after fresh data run]_

## License

MIT

## Citation

```bibtex
@misc{simpson2025astroscanr,
  author = {Simpson, Rob},
  title = {AstroScanr: Authorship Patterns in Astronomical Literature},
  year = {2025},
  url = {https://github.com/ttfnrob/astroscanr}
}
```

## Original Blog Post

https://web.archive.org/web/20140505050827/http://orbitingfrog.com/2012/08/04/authorship-in-astronomy/

---

_Part of Rob Simpson's personal research portfolio. Built with Python, ADS API, and matplotlib._
