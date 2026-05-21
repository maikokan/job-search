# Job Search Pipeline Refactor — Design Spec

## Context

The current job-search pipeline has three issues to address:
1. Config file lives in a `config/` subfolder; should be at project root
2. Two separate databases (`jobs.db`, `rejections.db`); should be one unified DB
3. LLM batch size is unbounded; needs configurable limits per stage
4. `--no-ai` skips enrichment but still runs GICS; should skip entire AI block

## Decisions

### 1. Config location
- Move `config/config.yaml` → `{project}/config.yaml`
- No home directory fallback
- `load_config()` in `cli.py` updated to look at project root

### 2. Single database
- Single `data/jobs.db` using existing schema
- `status TEXT DEFAULT 'active'` field with values `'active'` or `'rejected'`
- `rejection_reason TEXT` + `rejection_detail TEXT` already exist in schema
- `data/rejections.db` migrated on `setup_database()` — copy all rows from `job_rejections` into `jobs`, then drop the old table
- Migration runs once; safe to rerun (no duplicate inserts via `INSERT OR IGNORE`)

### 3. AI batch sizes
- Add `ai.classify_batch_size = 5` to config
- Add `ai.enrich_batch_size = 5` to config
- `classify_gics_batch()` loops over companies in batches of N
- `enrich_batch()` loops over jobs in batches of N

### 4. Pipeline behavior

| Flag | Scrape | Dedup | Filter | GICS Classify | Enrich | DB Write | Telegram | Prune |
|------|--------|-------|--------|---------------|--------|----------|----------|-------|
| Normal | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `--no-ai` | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| `--dry-run` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |

- `--no-ai`: Skip `classify_gics_batch`, `classify_gics_batch_retry`, and `enrich_batch` entirely. Jobs flow from filter directly to Telegram.
- `--dry-run`: Skip all DB writes (store_job, reject_and_remove, prune). Telegram still sends.

## Migration: rejections.db → jobs.db

On `setup_database()`:
1. Open `data/rejections.db` if it exists
2. SELECT all rows from `job_rejections`
3. INSERT OR IGNORE into `jobs` table
4. DROP TABLE job_rejections from rejections.db (or leave for manual cleanup)
5. Delete `data/rejections.db` after successful migration

If migration fails mid-way, it's idempotent — next run picks up where it left off.

## Config diff

```yaml
# Before
search: {terms, locations, hours_old, results_per_term}
scrapers: {sites, linkedin_fetch_description, max_workers}
database: {path, rejections_path, retention_days}
ai: {model, api_key, endpoint}

# After
search: {terms, locations, hours_old, results_per_term}
scrapers: {sites, linkedin_fetch_description, max_workers}
database: {path, retention_days}
ai: {model, api_key, endpoint, classify_batch_size, enrich_batch_size}
```