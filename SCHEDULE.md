# AstroScanr Weekly Update Schedule

## Rate Limit Context
- **ADS API**: 5000 requests / 86400 seconds (1 day)
- **Journals**: 13 total
- **Years**: 64 sampled
- **Per-run requests**: ~13 × 64 × 2-3 calls = 1,700-2,500 per journal set
- **Batching strategy**: 3-4 journals per week to stay under quota

## Weekly Schedule (Staggered Batches)

### Week 1 (Sunday 00:00 UTC)
**Core journals batch 1**: MNRAS, ApJ, A&A
- Rationale: Most cited, historical data most important
- Requests: ~384

### Week 2 (Sunday 00:00 UTC)
**Core journals batch 2**: AJ, PASP, NatAs
- Rationale: Remaining core + modern
- Requests: ~384

### Week 3 (Sunday 00:00 UTC)
**Secondary journals batch 1**: ApJL, PASA, MNRASLetters
- Rationale: Modern short-form papers
- Requests: ~384

### Week 4 (Sunday 00:00 UTC)
**Specialized journals**: AN, Icarus, SolPh, OJA
- Rationale: Field-specific + open access
- Requests: ~512

## Execution Steps

For each batch, run:
```bash
export ADS_API_KEY="..."
cd /home/rob/.openclaw/workspace/astroscanr
python3 astroscanr.py JOURNAL1 JOURNAL2 JOURNAL3
```

This fetches only the specified journals, merges with existing CSV, regenerates plots 01-06.

## Full Reanalysis (Monthly)
After all 4 batches complete (month cycle), run:
```bash
python3 astroscanr-extended.py  # Generates plots 07-10
```

## GitHub Actions Setup
Replace the current monthly cron (1st at 00:00 UTC) with:
- **Every Sunday at 00:00 UTC**: Batch rotation (cycle through 4 batches)
- **1st of month at 02:00 UTC**: Extended analysis (after all batches complete)

## Next Steps
1. Implement CSV merge logic in astroscanr.py
2. Update .github/workflows/update.yml with weekly Sunday schedule
3. Set environment for batch selection (e.g., via GitHub Actions matrix)
