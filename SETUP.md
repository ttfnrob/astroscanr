# AstroScanr: Setup & Maintenance Guide

## Quick Start

This repo has been pushed to GitHub at https://github.com/ttfnrob/astroscanr

The live demo site is at https://ttfnrob.github.io/astroscanr

## Running the Analysis Locally

### 1. Install dependencies

```bash
cd ~/workspace/astroscanr
pip install -r requirements.txt
```

### 2. Set your ADS API key

Get your API key from https://ui.adsabs.harvard.edu/user/settings/token (free, takes 2 minutes):

```bash
export ADS_API_KEY="your-token-here"
```

Or add it to ~/.bashrc or ~/.zshrc to persist it:

```bash
echo 'export ADS_API_KEY="your-token-here"' >> ~/.bashrc
source ~/.bashrc
```

### 3. Run the analysis

```bash
python3 astroscanr.py
```

This will:
1. Fetch data from NASA ADS API for MNRAS, ApJ, A&A, AJ, PASP (1827–2025)
2. Sample years: every 5 years before 1950, every 2 years after (63 total years)
3. Generate 6 plots as PNG files
4. Export stats to `astroscanr-stats.csv`

**Estimated time:** 10–15 minutes (API rate limiting)

## GitHub Setup

### Push to GitHub

To update the GitHub repo with fresh plots or data:

```bash
cd ~/workspace/astroscanr
git init
git config user.email "robert@orbitingfrog.com"
git config user.name "Robert Simpson"
git add -A
git commit -m "Update plots with fresh ADS data"
git branch -M main
git remote add origin https://github.com/ttfnrob/astroscanr.git
git push -u origin main  # Will prompt for token
```

You'll need to provide your GitHub Personal Access Token (with `repo` scope) when prompted.

### Enable GitHub Pages

1. Go to https://github.com/ttfnrob/astroscanr/settings/pages
2. Under "Source", select "Deploy from a branch"
3. Select branch: `main`
4. Select folder: `/ (root)`
5. Click "Save"

The site will be live at https://ttfnrob.github.io/astroscanr in ~1 minute.

### Update index.html with plots

After running the analysis, add the PNG files to the repo:

```bash
git add *.png astroscanr-stats.csv
git commit -m "Update plots with fresh 2025 data"
git push origin main
```

Then update `index.html` to reference the PNG files instead of placeholder divs.

## Publishing Updates

To publish fresh plots to GitHub, use a Personal Access Token with `repo` scope.
(See GitHub Settings > Developer Settings > Personal Access Tokens for yours.)

## Project Structure

```
astroscanr/
├── README.md                   # Main project documentation
├── SETUP.md                    # This file
├── astroscanr.py              # Main analysis script
├── requirements.txt            # Python dependencies
├── index.html                 # GitHub Pages home
├── .gitignore                 # Ignore generated files
├── .github/
│   └── workflows/
│       └── pages.yml          # GitHub Pages deploy (needs workflow scope)
├── astroscanr-stats.csv       # Generated: raw statistics
└── 0X-*.png                   # Generated: plots
```

## Troubleshooting

### API Rate Limiting

If you hit rate limits (errors like "429 Too Many Requests"):
- The script sleeps 0.1s between API calls
- For faster runs, edit `astroscanr.py` to sample fewer years
- Or run only recent years: change `YEARS = list(range(2000, 2026, 2))`

### Missing Imports

```bash
pip install --upgrade requests matplotlib pandas numpy
```

### API Key Issues

Test your API key:

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://api.adsabs.harvard.edu/v1/search/query?q=bibstem:MNRAS%20year:2020&rows=1"
```

Should return JSON with `numFound` and `docs`.

## Next Steps

1. Run the analysis locally to populate plots
2. Commit the plots to GitHub
3. Enable GitHub Pages in repo settings
4. Update index.html with embeds or links to PNG files
5. Write a blog post on orbitingfrog.com linking to the demo
