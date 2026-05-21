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

### 1. 7-Block Deep Evaluation
Replace the current single-shot summary + fit score with a structured 7-block evaluation inspired by career-ops:

| Block | Content |
|-------|---------|
| **A — Role Summary** | Archetype, domain, function, seniority, remote policy, team size, TL;DR |
| **B — CV Match** | JD requirements mapped to CV lines, per-archetype proof point prioritization, gap analysis with mitigation |
| **C — Level Strategy** | Detected vs target level, "sell senior" plan, downlevel negotiation approach |
| **D — Comp Research** | Salary ranges via WebSearch (Glassdoor, Levels.fyi), company comp reputation |
| **E — Customization Plan** | Top 5 CV changes + top 5 LinkedIn changes for the specific role |
| **F — Interview Plan** | STAR+R stories mapped to JD requirements, story bank reuse |
| **G — Posting Legitimacy** | Ghost job detection — posting age, apply button state, JD quality, reposting patterns |

**Implementation notes:**
- Archetypes: LLMOps, Agentic, FDE, SA, PM, Transformation
- Per-archetype evaluation framing (different proof points per type)
- Store full evaluation in DB alongside job record
- Telegram notifications include block-level highlights, not just summary

### 2. Ghost Job Detection (Block G)
Assess whether a job posting is real and active before surfacing it:

**Signals to analyze:**
- Posting age (from page content or "X days ago" text)
- Apply button state (active / closed / redirects to generic)
- URL redirect patterns (careers page redirect = high confidence of closure)
- JD quality (generic boilerplate vs role-specific details)
- Requirements realism (contradictions like "entry-level title + staff requirements")
- Company hiring signals (WebSearch for layoffs, hiring freezes)
- Reposting detection (same company + role seen before in scan history)

**Implementation notes:**
- Run after scraping, before GICS classification
- Store legitimacy tier (High Confidence / Proceed with Caution / Suspicious) in DB
- Jobs flagged as Suspicious are still stored but marked with warning
- Telegram notification can include legitimacy indicator

### 3. Story Bank
Build a reusable interview story bank across all evaluated jobs:

**STAR+R format per story:**
- Situation, Task, Action, Result, + Reflection (signals seniority)

**Implementation notes:**
- `data/story-bank.md` accumulates stories across evaluations
- Stories tagged by theme/skill (e.g., "leadership", "technical challenge", "conflict")
- During Block F (Interview Plan), existing stories are matched to new JD requirements
- Stories are deduplicated and merged when similar situations arise
- Per-archetype story framing (FDE prioritizes delivery speed stories, SA prioritizes architectural decisions, etc.)
- Write new stories to `data/story-bank.md` only when no existing story matches the JD requirement

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
- `data/story-bank.md` — interview story bank (planned)
- DB paths are relative to project root, auto-created on first run

## Quirks
- Job IDs are `SHA256(url)[:16]` — stable across runs
- `load_config()` searches: (1) explicit `--config` path, (2) `config/config.yaml` relative to project root, (3) `~/.hermes/.../job-search-workflow/config.yaml`
- Telegram creds search: `.env` in project root, then `~/.hermes/.env`
- Guangdong is always rejected from location filter
- `python-jobspy` is the scraper library (installed as dependency)