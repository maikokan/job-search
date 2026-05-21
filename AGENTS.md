# AGENTS.md

## Project Overview
Job scraping tool that searches LinkedIn, classifies companies by GICS codes, enriches listings with AI summaries/fit scores, and sends results via Telegram.

## Commands

### Running
```bash
uv run job-search --help
uv run job-search --hours-old 48        # Override hours filter
uv run job-search --no-ai               # Skip AI (scrape + store only)
uv run job-search --dry-run             # No DB writes, no notifications
```

### Development
```bash
uv run ruff check src/        # Lint
uv run mypy src/               # Type check
```

## Architecture

```
src/job_search/
  cli.py         # Entry point; orchestrates scrape → classify → enrich → notify
  scrape.py      # Parallel scraping via python-jobspy (ThreadPoolExecutor, max_workers=8)
  gics.py        # GICS classification via LLM; handles batch + retry
  enrich.py      # AI summary + fit score via LLM
  db.py          # SQLite jobs.db and rejections.db
  telegram.py    # Telegram bot notifications (reads .env)
```

**Pipeline flow (cli.py main()):**
1. `search_all()` — parallel scrape
2. Dedupe by URL SHA256 hash
3. `filter_location()` — reject "Guangdong" jobs (leaky from HK searches)
4. `filter_by_reject_words()` — title rejection
5. `classify_gics_batch()` + retry
6. `enrich_batch()` — AI summary/score
7. Store to DB
8. `notify_telegram()`
9. `prune_old()` — delete jobs older than `retention_days`

## Planned Enhancements

### 1. Enhanced Role Summary
Replace the current single-shot summary + fit score with a richer role summary:

**Content:**
- **Archetype** — LLMOps / Agentic / FDE / SA / PM / Transformation
- **Domain** — platform, ML, enterprise, voice AI, etc.
- **Function** — build / consult / manage / deploy
- **Seniority** — inferred level from JD language
- **Remote policy** — full remote / hybrid / onsite
- **Team size** — if mentioned in JD
- **TL;DR** — 1 sentence summary

**Rationale:**
- Different archetypes prioritize different proof points — a LLMOps role values observability and evals differently than an FDE role
- Per-archetype framing makes summaries more actionable and relevant
- Currently `enrich.py` uses a generic "recent graduate with finance/engineering background" — this adapts to the actual role type

**Implementation notes:**
- Add `archetype` field to jobs DB
- Refactor `enrich.py` to output structured summary fields instead of free-text summary + score
- Archetype detection via keyword matching (see archetypes in career-ops `_shared.md`)

## Config
Edit `config/config.yaml`. Key sections:
- `ai` — model, api_key, endpoint (default: localhost:20128)
- `search` — terms, locations, hours_old, results_per_term
- `scrapers.sites` — list of job boards (default: linkedin)
- `database.path` — relative to app root (data/jobs.db)
- `desired_gics` / `rejected_gics` — 8-digit GICS codes
- `reject_words` — title patterns to exclude

## Dependencies & Environment
- Python ≥3.10 with uv
- `.env` file in project root for Telegram credentials:
  ```
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CRON_CHANNEL=...
  ```
- LLM endpoint must be accessible for GICS classification and enrichment

## Database
- `data/jobs.db` — stored jobs (auto-created via sqlite3)
- `data/rejections.db` — rejected jobs with reasons
- DB paths are relative to project root, auto-created on first run

## Quirks
- Job IDs are `SHA256(url)[:16]` — stable across runs
- `load_config()` searches: (1) explicit `--config` path, (2) `config/config.yaml` relative to project root, (3) `~/.hermes/.../job-search-workflow/config.yaml`
- Telegram creds search: `.env` in project root, then `~/.hermes/.env`
- Guangdong is always rejected from location filter
- `python-jobspy` is the scraper library (installed as dependency)