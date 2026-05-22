"""Database operations for job scraping."""
import datetime
import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


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

    # Get actual columns present in rejections.db
    cur = rej_conn.execute("PRAGMA table_info(job_rejections)")
    actual_cols = [row[1] for row in cur.fetchall()]

    placeholders = ', '.join(['?'] * len(actual_cols))

    cur = rej_conn.execute(f"SELECT {', '.join(actual_cols)} FROM job_rejections")
    for row in cur.fetchall():
        try:
            conn.execute(f"INSERT OR IGNORE INTO jobs ({', '.join(actual_cols)}) VALUES ({placeholders})", row)
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


def job_id(url: str) -> str:
    """Deterministic ID for dedup — based on URL only."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def setup_database(db_path: str | Path) -> sqlite3.Connection:
    """Create jobs DB + table if needed. Returns connection."""
    db_path = Path(db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT,
            job_type TEXT,
            is_remote INTEGER,
            description TEXT,
            summary TEXT,
            industry TEXT,
            gics_code INTEGER,
            gics_confidence REAL,
            fit_score REAL,
            enriched_at TEXT,
            notified INTEGER DEFAULT 0,
            scraped_at TEXT,
            status TEXT DEFAULT 'active',
            rejection_reason TEXT,
            rejection_detail TEXT
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC)")

    # Migrate: add new columns if upgrading from old schema
    for col, coldef in [
        ('status', "TEXT DEFAULT 'active'"),
        ('rejection_reason', 'TEXT'),
        ('rejection_detail', 'TEXT'),
    ]:
        try:
            conn.execute(f'ALTER TABLE jobs ADD COLUMN {col} {coldef}')
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()

    # Create index after column exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    # Migrate rejections.db into jobs.db
    rej_path = Path(str(db_path).replace('jobs.db', 'rejections.db'))
    _migrate_rejections(conn, rej_path)

    return conn


def reject_and_remove(conn: sqlite3.Connection, job: Dict, reason: str, detail: str = '') -> None:
    """Mark job as rejected (status='rejected')."""
    jid = job_id(job.get('url', ''))
    conn.execute(
        "UPDATE jobs SET status='rejected', rejection_reason=?, rejection_detail=? WHERE id=?",
        (reason, detail, jid)
    )
    conn.commit()


def store_job(conn: sqlite3.Connection, job: Dict) -> bool:
    """Store a single job. Returns True if stored (new), False if duplicate."""
    jid = job_id(job.get('url', ''))
    try:
        conn.execute('''
            INSERT OR IGNORE INTO jobs
            (id, title, company, location, url,
             job_type, is_remote, description, summary, industry, gics_code,
             gics_confidence, fit_score, enriched_at, notified, scraped_at,
             status, rejection_reason, rejection_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            jid, job.get('title'), job.get('company'), job.get('location'), job.get('url'),
            job.get('job_type'), int(job.get('is_remote', False)),
            job.get('description'), job.get('summary'), job.get('industry'),
            job.get('gics_code'), job.get('gics_confidence'), job.get('fit_score'),
            job.get('enriched_at'), int(job.get('notified', False)),
            job.get('scraped_at'),
            'active',  # default status
            None,      # rejection_reason
            None,      # rejection_detail
        ))
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


def prune_old(conn: sqlite3.Connection, retention_days: int):
    """Delete jobs older than retention period."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=retention_days)).isoformat()
    conn.execute('DELETE FROM jobs WHERE scraped_at < ?', (cutoff,))
    conn.commit()


def is_duplicate(conn: sqlite3.Connection, url: str) -> bool:
    """Check if job URL already exists in DB."""
    jid = job_id(url)
    cur = conn.cursor()
    cur.execute('SELECT id FROM jobs WHERE id = ?', (jid,))
    return cur.fetchone() is not None
