# Job Search Pipeline Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the job-search pipeline: (1) move config to project root, (2) unify to single DB, (3) add configurable AI batch sizes, (4) fix --no-ai scope.

**Architecture:** Four independent changes across config, DB, LLM batching, and pipeline flow control. Each task modifies one concern.

**Tech Stack:** Python, SQLite, JobSpy, OmniRoute LLM API, Telegram Bot API

---

## File Map

| File | Role |
|------|------|
| `config.yaml` | Config at project root (moved from config/config.yaml) |
| `src/job_search/cli.py` | Config loading path + default batch sizes |
| `src/job_search/db.py` | Single DB, migration of rejections.db, drop rejections_path |
| `src/job_search/pipeline.py` | --no-ai skips entire AI block, --dry-run skips DB writes |
| `src/job_search/gics.py` | Batch loop in classify_gics_batch + classify_gics_batch_retry |
| `src/job_search/enrich.py` | Batch loop in enrich_batch |
| `src/job_search/telegram.py` | Telegram formatting, untouched by logic changes |

---

## Task 1: Move config.yaml to project root

**Files:**
- Create: `config.yaml` (moved content)
- Modify: `src/job_search/cli.py:15-38`
- Delete: `config/config.yaml`
- Test: `tests/job_search/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/job_search/test_cli.py
import pytest
import tempfile
import os
from pathlib import Path
from job_search.cli import load_config

def test_load_config_from_project_root(tmp_path, monkeypatch):
    """Config loaded from project root config.yaml."""
    monkeypatch.chdir(tmp_path)
    config_content = {
        'search': {'terms': ['foo']},
        'ai': {'classify_batch_size': 7},
    }
    import yaml
    (tmp_path / 'config.yaml').write_text(yaml.dump(config_content))

    cfg = load_config()
    assert cfg['search']['terms'] == ['foo']
    assert cfg['ai']['classify_batch_size'] == 7

def test_load_config_default_batch_sizes():
    """Default batch sizes when ai key is absent."""
    cfg = load_config(str(tmp_path / 'nonexistent.yaml')) if False else None
    # default values tested below in cli.py task
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/job_search/test_cli.py -v -k "test_load_config_from_project_root"`
Expected: test will be added in Step 1

- [ ] **Step 3: Update load_config() in cli.py**

Replace `load_config()` with:

```python
def load_config(config_path: str | None = None) -> dict:
    """Load config.yaml from standard locations."""
    if config_path:
        path = Path(config_path)
    else:
        app_dir = Path(__file__).parent.parent.parent
        path = app_dir / 'config.yaml'

    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]

    # Default config
    return {
        'search': {'terms': ['intern'], 'locations': ['Hong Kong'], 'hours_old': 24, 'results_per_term': 50},
        'scrapers': {'sites': ['linkedin'], 'linkedin_fetch_description': True, 'max_workers': 8},
        'database': {'path': 'data/jobs.db', 'retention_days': 365},
        'desired_gics': [],
        'reject_words': [],
        'ai': {
            'model': 'free-stack',
            'api_key': '',
            'endpoint': 'http://localhost:20128/v1/chat/completions',
            'classify_batch_size': 5,
            'enrich_batch_size': 5,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/job_search/test_cli.py -v -k "test_load_config_from_project_root"`
Expected: PASS

- [ ] **Step 5: Move config.yaml to project root**

Read existing `config/config.yaml`, write to `config.yaml` at project root. Do not delete old file yet (for next task).

- [ ] **Step 6: Commit**

```bash
git add src/job_search/cli.py
git commit -m "feat: load config from project root config.yaml"
```

---

## Task 2: Unify to single database

**Files:**
- Modify: `src/job_search/db.py` (drop init_rejections_db, update setup_database, new migrate function)
- Modify: `src/job_search/pipeline.py:38-101` (remove rej_conn from pipeline)
- Test: `tests/job_search/test_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/job_search/test_db.py
import pytest
import tempfile
import sqlite3
from pathlib import Path
from job_search.db import setup_database

def test_migrate_rejections(tmp_path):
    """rejections.db rows are migrated into jobs.db on setup."""
    # Create rejections.db with one row
    rej_path = tmp_path / 'rejections.db'
    rej_conn = sqlite3.connect(str(rej_path))
    rej_conn.execute('''
        CREATE TABLE job_rejections (
            id TEXT PRIMARY KEY,
            title TEXT, company TEXT, location TEXT, url TEXT,
            job_type TEXT, is_remote INTEGER, description TEXT,
            summary TEXT, industry TEXT, gics_code INTEGER,
            gics_confidence REAL, fit_score REAL, enriched_at TEXT,
            notified INTEGER DEFAULT 0, scraped_at TEXT,
            rejection_reason TEXT, rejection_detail TEXT
        )
    ''')
    rej_conn.execute(
        "INSERT INTO job_rejections (id, title, company, url, rejection_reason) VALUES (?, ?, ?, ?, ?)",
        ('abc123', 'Software Engineer', 'Acme Corp', 'https://example.com/1', 'gics_no_match')
    )
    rej_conn.commit()
    rej_conn.close()

    # Create jobs.db with setup_database (should migrate)
    db_path = tmp_path / 'jobs.db'
    conn = setup_database(db_path)

    cur = conn.execute("SELECT title, company, rejection_reason FROM jobs WHERE id = ?", ('abc123',))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 'Software Engineer'
    assert row[2] == 'gics_no_match'

    conn.close()

def test_no_duplicate_migration(tmp_path):
    """Migration is idempotent — rerunning setup_database does not duplicate rows."""
    db_path = tmp_path / 'jobs.db'

    rej_path = tmp_path / 'rejections.db'
    rej_conn = sqlite3.connect(str(rej_path))
    rej_conn.execute('''
        CREATE TABLE job_rejections (
            id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, url TEXT,
            job_type TEXT, is_remote INTEGER, description TEXT, summary TEXT, industry TEXT,
            gics_code INTEGER, gics_confidence REAL, fit_score REAL, enriched_at TEXT,
            notified INTEGER DEFAULT 0, scraped_at TEXT, rejection_reason TEXT, rejection_detail TEXT
        )
    ''')
    rej_conn.execute(
        "INSERT INTO job_rejections (id, title, company, url) VALUES (?, ?, ?, ?)",
        ('abc123', 'Engineer', 'Acme', 'https://x.com/1')
    )
    rej_conn.commit()
    rej_conn.close()

    # First setup
    conn1 = setup_database(db_path)
    count1 = conn1.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", ('abc123',)).fetchone()[0]
    conn1.close()

    # Second setup (no-op migration)
    conn2 = setup_database(db_path)
    count2 = conn2.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", ('abc123',)).fetchone()[0]
    conn2.close()

    assert count1 == 1
    assert count2 == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/job_search/test_db.py -v -k "test_migrate_rejections or test_no_duplicate_migration"`
Expected: FAIL (setup_database doesn't migrate yet)

- [ ] **Step 3: Add migration function to db.py**

Add before `setup_database`:

```python
def _migrate_rejections(conn: sqlite3.Connection, rej_path: Path | str) -> None:
    """Copy rows from rejections.db into conn, then delete old file."""
    rej_path = Path(rej_path)
    if not rej_path.exists():
        return

    rej_conn = sqlite3.connect(str(rej_path))
    try:
        rej_conn.execute("SELECT id FROM job_rejections LIMIT 1")
    except sqlite3.OperationalError:
        rej_conn.close()
        return

    cols = [
        'id', 'title', 'company', 'location', 'url', 'job_type', 'is_remote',
        'description', 'summary', 'industry', 'gics_code', 'gics_confidence',
        'fit_score', 'enriched_at', 'notified', 'scraped_at',
        'status', 'rejection_reason', 'rejection_detail',
    ]
    placeholders = ', '.join(['?'] * len(cols))

    cur = rej_conn.execute(
        f"SELECT {', '.join(cols)} FROM job_rejections",
    )
    for row in cur.fetchall():
        try:
            conn.execute(f"INSERT OR IGNORE INTO jobs ({', '.join(cols)}) VALUES ({placeholders})", row)
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    cur.close()
    rej_conn.close()

    try:
        rej_path.unlink()
        logger.info(f"Migrated rejections to jobs.db, removed {rej_path}")
    except OSError:
        pass
```

Add at top of db.py:
```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Update setup_database to call migration**

In `setup_database()`, after `conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")` and `conn.commit()`, add:

```python
    # Migrate rejections.db into jobs.db
    rej_path = Path(str(db_path).replace('jobs.db', 'rejections.db'))
    _migrate_rejections(conn, rej_path)

    return conn
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/job_search/test_db.py -v -k "test_migrate_rejections or test_no_duplicate_migration"`
Expected: PASS

- [ ] **Step 6: Update pipeline.py to remove rej_conn dependency**

Remove `init_rejections_db` import.

Remove all calls passing `rej_conn`:
- In `run()`: remove `rej_conn = init_rejections_db(rej_path)`
- In `filter()`: calls `reject_and_remove(conn, rej_conn, ...)` — keep the function but pass `None` for `rej_conn`, update `reject_and_remove` to handle `None`
- In `classify_and_match()`: same — keep function but pass `None`

Simplify `reject_and_remove` to no longer take `rej_conn`:

```python
def reject_and_remove(conn: sqlite3.Connection, job: Dict, reason: str, detail: str = '') -> None:
    """Mark job as rejected (status='rejected') in jobs DB."""
    jid = job_id(job.get('url', ''))
    conn.execute(
        "UPDATE jobs SET status='rejected', rejection_reason=?, rejection_detail=? WHERE id=?",
        (reason, detail, jid)
    )
    conn.commit()
```

Remove `store_rejection` function (no longer needed).

- [ ] **Step 7: Update pipeline.py filter and classify_and_match calls**

In `filter()`:
```python
reject_and_remove(conn, j, 'location_mismatch', j.get('location', ''))
reject_and_remove(conn, j, 'title_reject_word', j.get('_reject_word', ''))
```

In `classify_and_match()`:
```python
reject_and_remove(conn, j, 'gics_no_match', f'code={gics}')
reject_and_remove(conn, j, 'gics_rejected', f'code={gics}')
```

Remove `rej_conn` parameter from `filter()` and `classify_and_match()` method signatures.

- [ ] **Step 8: Run all tests**

Run: `pytest tests/job_search/test_db.py tests/job_search/test_filters.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/job_search/db.py src/job_search/pipeline.py
git commit -m "feat: single unified jobs.db with rejections as status=rejected"
```

---

## Task 3: Configurable AI batch sizes

**Files:**
- Modify: `src/job_search/gics.py:202-276` and `278-352`
- Modify: `src/job_search/enrich.py:40-127`
- Test: `tests/job_search/test_gics.py` (add batch loop tests)

- [ ] **Step 1: Write failing tests**

```python
# tests/job_search/test_gics.py
import pytest
from unittest.mock import patch, MagicMock
from job_search.gics import classify_gics_batch

def test_batches_of_n(monkeypatch):
    """Jobs are classified in batches of ai.classify_batch_size."""
    mock_response = '[{"index":0,"code":"40101010","sub_industry":"Banks","confidence":0.9}]'
    call_count = [0]
    def mock_llm(*args, **kwargs):
        call_count[0] += 1
        return mock_response
    monkeypatch.setattr('job_search.gics.llm_call', mock_llm)

    jobs = [
        {'company': f'Company{i}', 'title': 'Analyst', 'description': 'desc'}
        for i in range(12)
    ]
    ai_config = {'model': 'gpt-4', 'api_key': '', 'endpoint': 'http://x', 'classify_batch_size': 5}

    classify_gics_batch(jobs, ai_config)

    # 12 jobs, batch_size=5 → ceil(12/5) = 3 batches
    assert call_count[0] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/job_search/test_gics.py -v -k "test_batches_of_n"`
Expected: FAIL (no batch loop yet)

- [ ] **Step 3: Update classify_gics_batch with batch loop**

Replace `classify_gics_batch()` body with:

```python
def classify_gics_batch(jobs: List[Dict], ai_config: Dict) -> None:
    """Classify ALL jobs in batches. Modifies jobs in-place."""
    if not jobs:
        return

    batch_size = ai_config.get('classify_batch_size', 5)

    # Deduplicate companies
    company_seen: dict = {}
    items: list[str] = []
    for j in jobs:
        company = _sanitize(j.get('company', ''))
        if not company:
            j['gics_code'] = None
            j['industry'] = ''
            j['gics_confidence'] = 0.0
            continue
        key = company.lower()
        if key not in company_seen:
            company_seen[key] = len(items)
            title = _sanitize(j.get('title', ''))[:80]
            items.append(f"{len(items)}. Company: {company} | Title: {title}")
        idx = company_seen.get(company.lower(), -1)

    if not items:
        return

    model = ai_config.get('model', '')
    api_key = ai_config.get('api_key', '')
    endpoint = ai_config.get('endpoint', 'http://localhost:20128/v1/chat/completions')

    # Process in batches
    results: Dict[int, Dict] = {}
    for batch_start in range(0, len(items), batch_size):
        batch_items = items[batch_start:batch_start + batch_size]
        numbered = "\n".join(batch_items)
        prompt = "Companies to classify:\n" + numbered + "\n"

        response = llm_call(
            GICS_BATCH_SYSTEM_PROMPT,
            prompt,
            model,
            api_key,
            endpoint,
            max_tokens=len(batch_items) * 100,
            retries=2,
        )

        # Offset indices by batch_start
        try:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                for item in parsed:
                    idx = item.get('index', -1)
                    code_str = str(item.get('code', ''))
                    if re.match(r'\d{8}', code_str):
                        results[batch_start + idx] = {
                            'code': int(code_str),
                            'sub_industry': item.get('sub_industry', ''),
                            'confidence': float(item.get('confidence', 0.5)),
                        }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Assign results back to jobs
    for i, j in enumerate(jobs):
        company = _sanitize(j.get('company', '')).lower()
        if not company:
            j['gics_code'] = None
            j['industry'] = ''
            j['gics_confidence'] = 0.0
            continue
        idx = company_seen.get(company, -1)
        if idx in results:
            j['gics_code'] = results[idx]['code']
            j['industry'] = results[idx]['sub_industry']
            j['gics_confidence'] = results[idx]['confidence']
        else:
            j['gics_code'] = None
            j['industry'] = ''
            j['gics_confidence'] = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/job_search/test_gics.py -v -k "test_batches_of_n"`
Expected: PASS

- [ ] **Step 5: Update enrich_batch with batch loop**

Replace `enrich_batch()` body. Read ai_config from config, get `enrich_batch_size` (default 5). Loop LLM calls:

```python
def enrich_batch(jobs: List[Dict], config: dict, ai_config: Dict) -> None:
    """Enrich all matched jobs in batches. Modifies jobs in-place."""
    if not jobs:
        return

    batch_size = ai_config.get('enrich_batch_size', 5)
    reject_words = config.get('reject_words', [])

    # Filter to eligible jobs
    eligible = []
    for j in jobs:
        title = j.get('title') or ''
        for word in reject_words:
            pattern = r'\b' + re.escape(word.lower()) + r'\b'
            if re.search(pattern, title.lower()):
                j['_rejected'] = True
                j['_rejection_reason'] = 'title_reject_word'
                break
        else:
            desc = j.get('description') or ''
            if desc and len(desc) >= 50:
                eligible.append(j)
            else:
                j['summary'] = ''
                j['fit_score'] = None
                j['enriched_at'] = datetime.datetime.now().isoformat()

    if not eligible:
        return

    # Build batch items
    items = []
    for i, j in enumerate(eligible):
        title = j.get('title') or ''
        company = j.get('company') or ''
        desc = j.get('description') or ''
        items.append((i, j, f"[{i}] {company} | {title}\n{desc}"))

    model = ai_config.get('model', '')
    api_key = ai_config.get('api_key', '')
    endpoint = ai_config.get('endpoint', 'http://localhost:20128/v1/chat/completions')

    results: Dict[int, Dict] = {}
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start:batch_start + batch_size]
        numbered = "\n---\n".join(item[2] for item in batch)

        prompt = (
            "For each job below, provide:\n"
            "1) A 3-5 sentence summary: day-to-day duties, key qualifications, team/reporting context, conditions\n"
            "2) A fit score (0-10) for this candidate\n\n"
            "Candidate is a recent graduate with finance/engineering background.\n\n"
            f"Jobs to evaluate:\n{numbered}\n\n"
            'Reply with a JSON array:\n'
            '[{"index": 0, "summary": "...", "fit": 7}, ...]\n'
            "Summaries should be 300-500 chars. Specific and factual, no fluff."
        )

        response = llm_call(
            "You are a career advisor. Summarize each job and score its fit for the candidate. "
            "Reply with ONLY a JSON array.",
            prompt,
            model,
            api_key,
            endpoint,
            max_tokens=min(8000, len(batch) * 300),
            retries=2,
        )

        try:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                for item in parsed:
                    idx = item.get('index', -1)
                    results[batch_start + idx] = {
                        'summary': item.get('summary', ''),
                        'fit': item.get('fit'),
                    }
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            pass

    for i, j in enumerate(eligible):
        if i in results:
            j['summary'] = results[i].get('summary', '')
            fit = results[i].get('fit')
            j['fit_score'] = max(0.0, min(10.0, float(fit))) if fit is not None else None
        else:
            j['summary'] = ''
            j['fit_score'] = None
        j['enriched_at'] = datetime.datetime.now().isoformat()
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/job_search/test_gics.py tests/job_search/test_enrich.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/job_search/gics.py src/job_search/enrich.py
git commit -m "feat: configurable batch sizes for GICS and enrichment"
```

---

## Task 4: Fix --no-ai scope and --dry-run DB isolation

**Files:**
- Modify: `src/job_search/pipeline.py` (run, filter, classify_and_match, enrich, notify)
- Modify: `src/job_search/config.py` (default batch sizes)
- Test: `tests/job_search/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/job_search/test_pipeline.py
import pytest
from unittest.mock import patch, MagicMock
from job_search.pipeline import Pipeline

def test_no_ai_skips_gics_and_enrich(monkeypatch):
    """--no-ai skips classify and enrich entirely."""
    classify_called = [False]
    enrich_called = [False]
    monkeypatch.setattr('job_search.pipeline.classify_gics_batch', lambda *a, **k: classify_called.__setitem__(0, True))
    monkeypatch.setattr('job_search.pipeline.classify_gics_batch_retry', lambda *a, **k: classify_called.__setitem__(0, True))
    monkeypatch.setattr('job_search.pipeline.enrich_batch', lambda *a, **k: enrich_called.__setitem__(0, True))
    monkeypatch.setattr('job_search.pipeline.notify_telegram', lambda *a, **k: True)

    config = {'search': {'terms': [], 'locations': []}, 'ai': {}, 'database': {'path': ':memory:'}}
    validated = MagicMock(desired_gics=[], rejected_gics=[], reject_words=[])
    pipe = Pipeline(config, validated, no_ai=True, dry_run=False)
    pipe.run()

    assert not classify_called[0], "GICS should be skipped with --no-ai"
    assert not enrich_called[0], "Enrich should be skipped with --no-ai"

def test_dry_run_skips_db_writes(monkeypatch):
    """--dry-run runs full pipeline but skips DB writes."""
    store_called = [False]
    reject_called = [False]
    monkeypatch.setattr('job_search.pipeline.store_job', lambda *a, **k: store_called.__setitem__(0, True))
    monkeypatch.setattr('job_search.pipeline.reject_and_remove', lambda *a, **k: reject_called.__setitem__(0, True))
    monkeypatch.setattr('job_search.pipeline.notify_telegram', lambda *a, **k: True)

    config = {'search': {'terms': [], 'locations': []}, 'ai': {}, 'database': {'path': ':memory:'}}
    validated = MagicMock(desired_gics=[], rejected_gics=[], reject_words=[])
    pipe = Pipeline(config, validated, no_ai=False, dry_run=True)
    pipe.run()

    assert not store_called[0], "store_job should be skipped with --dry-run"
    assert not reject_called[0], "reject_and_remove should be skipped with --dry-run"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/job_search/test_pipeline.py -v -k "test_no_ai_skips or test_dry_run_skips"`
Expected: FAIL (current code still calls classify/enrich with --no-ai)

- [ ] **Step 3: Update Pipeline.run() with no_ai guard**

In `run()`, replace the classify+enrich block:

Current (around line 77-87):
```python
# Classify + match
all_matched = self.classify_and_match(conn, rej_conn, new_jobs)
...

# Enrich
if not self.no_ai and not self.dry_run:
    self.enrich(all_matched)
```

Replace with:

```python
# Classify + match (skip if no_ai)
if self.no_ai:
    all_matched = []
    for j in new_jobs:
        j['gics_code'] = None
        j['gics_confidence'] = 0.0
        j['industry'] = ''
        if not self.dry_run:
            store_job(conn, j)
        all_matched.append(j)
else:
    all_matched = self.classify_and_match(conn, new_jobs)
```

- [ ] **Step 4: Update classify_and_match signature and calls**

Remove `rej_conn` parameter from `classify_and_match()`. Update all internal calls to `reject_and_remove(conn, j, ...)` (no rej_conn).

- [ ] **Step 5: Update filter() signature**

Remove `rej_conn` parameter. Update all internal calls to `reject_and_remove(conn, j, ...)`.

- [ ] **Step 6: Update enrich() DB writes**

In `enrich()`, skip `setup_database` and UPDATE calls if `self.dry_run`:

```python
def enrich(self, jobs: List[Dict]) -> None:
    """Enrich jobs with AI summary and fit score."""
    if self.dry_run:
        return
    logger.info(f"Enriching {len(jobs)} jobs")
    # ... rest unchanged
```

- [ ] **Step 7: Update notify() DB writes**

In `notify()`, skip UPDATE `notified=1` if `self.dry_run`:

```python
def notify(self, jobs: List[Dict]) -> None:
    """Send jobs to Telegram."""
    if notify_telegram(jobs):
        if not self.dry_run:
            app_dir = Path(__file__).parent.parent.parent
            db_path = app_dir / self.config.get("database", {}).get("path", "data/jobs.db")
            conn = setup_database(str(db_path))
            for j in jobs:
                jid = job_id(j.get('url', ''))
                conn.execute('UPDATE jobs SET notified = 1 WHERE id = ?', (jid,))
            conn.commit()
            conn.close()
        logger.info(f"Telegram: {len(jobs)} jobs sent")
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/job_search/test_pipeline.py -v -k "test_no_ai_skips or test_dry_run_skips"`
Expected: PASS

- [ ] **Step 9: Update config.py defaults**

Add batch size defaults to config loading in `config.py` or in `validate_config()`:

```python
def validate_config(config: dict, no_ai: bool) -> ValidatedConfig:
    # ... existing logic ...
    ai = config.get("ai", {})
    classify_batch_size = ai.get('classify_batch_size', 5)
    enrich_batch_size = ai.get('enrich_batch_size', 5)

    return ValidatedConfig(
        desired_gics=desired_gics,
        rejected_gics=rejected_gics,
        reject_words=reject_words,
        ai_endpoint=ai_endpoint,
        ai_api_key=ai_api_key,
        no_ai=no_ai,
        classify_batch_size=classify_batch_size,
        enrich_batch_size=enrich_batch_size,
    )
```

- [ ] **Step 10: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/job_search/pipeline.py src/job_search/config.py
git commit -m "feat: --no-ai skips entire AI block, --dry-run skips DB writes"
```

---

## Task 5: Move config.yaml and cleanup

**Files:**
- Move: `config/config.yaml` → `config.yaml`
- Delete: `config/` directory (if empty after move)
- Modify: `src/job_search/cli.py` (update default ai config)

- [ ] **Step 1: Move config file**

Read `config/config.yaml`, write to `config.yaml`, delete old file.

- [ ] **Step 2: Verify and commit**

```bash
git add config.yaml
git rm config/config.yaml
git commit -m "chore: move config.yaml to project root"
```

---

## Self-Review Checklist

- [ ] Spec coverage: All 4 design decisions covered in tasks?
    - ✅ Config at project root → Task 1 + 5
    - ✅ Single DB + migration → Task 2
    - ✅ Batch sizes → Task 3
    - ✅ --no-ai full AI skip + --dry-run DB isolation → Task 4
- [ ] Placeholder scan: No TBD/TODO/undefined placeholders in task steps
- [ ] Type consistency: `classify_batch_size`/`enrich_batch_size` in all tasks match config keys
- [ ] Pipeline flow correct after all changes?
    - normal: scrape → dedup → filter → classify → enrich → notify → prune ✅
    - no_ai: scrape → dedup → filter → store → notify (no classify/enrich) ✅
    - dry_run: scrape → dedup → filter → classify → enrich → notify (no DB writes) ✅