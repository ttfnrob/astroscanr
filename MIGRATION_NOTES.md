# Migration Notes

## 2026-07-18 — Rollup sentinel + daily quota reset + checkpoint reset

These are one-time manual steps to run **after** deploying the code changes
in this commit. The code changes themselves are backward-safe, but the
existing `astroscanr.db` carries stale state that should be cleaned once.

### 1. Purge stale NULL-journal rollup rows (FIX A)

Rollup rows are now stored with `journal = 'ALL'` instead of `journal = NULL`.
The next pipeline run writes the new 'ALL' rows via upsert, but the old
NULL rows remain until deleted. Run once:

```sh
sqlite3 astroscanr.db "DELETE FROM yearly_stats WHERE journal IS NULL;"
```

(Safe to run repeatedly; it only removes legacy NULL rollup rows.)

### 2. Reset the checkpoint (FIX C)

The persisted checkpoint has a stale journal index / quota / completed list
that should be reset so the next run starts clean. Run once:

```sh
sqlite3 astroscanr.db "UPDATE checkpoint SET next_journal_idx=0, requests_used=0, completed_journals='[]', last_run=0;"
```

Notes:
- `last_run=0` is interpreted by the daily-quota-reset logic (FIX B) as an
  epoch timestamp far in the past, so the first run after reset will treat
  the quota as fresh (requests_used reset to 0). This is the intended
  behavior.
- After the reset, the daily ADS quota counter (FIX B) automatically
  resets `requests_used` to 0 whenever the last successful run was more
  than 24h (86400s) ago — no further manual intervention needed.

### Order

Run step 1 then step 2. Both are idempotent-safe to run once on the
production `astroscanr.db` before (or immediately after) the first
post-deploy pipeline run.
