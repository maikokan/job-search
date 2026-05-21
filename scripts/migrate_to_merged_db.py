"""Migrate from two-DB setup to single merged DB with WAL mode."""
import sqlite3
from pathlib import Path


def migrate():
    """Merge jobs.db and rejections.db into a single DB with unified schema."""
    jobs_db = Path("data/jobs.db")
    rej_db = Path("data/rejections.db")
    merged_db = Path("data/jobs_merged.db")

    if not jobs_db.exists() and not rej_db.exists():
        print("No databases found, nothing to migrate")
        return

    # Create merged DB with WAL mode
    conn = sqlite3.connect(str(merged_db))
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC)")
    conn.commit()

    # Migrate active jobs from jobs.db
    if jobs_db.exists():
        src = sqlite3.connect(str(jobs_db))
        for row in src.execute("SELECT * FROM jobs"):
            # Pad with None for new columns: status, rejection_reason, rejection_detail
            conn.execute(
                "INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row + (None, None, None)
            )
        src.close()
        print(f"Migrated {jobs_db} -> {merged_db}")

    # Migrate rejections from rejections.db
    if rej_db.exists():
        src = sqlite3.connect(str(rej_db))
        for row in src.execute("SELECT * FROM job_rejections"):
            # row has all original columns, add status='rejected' + rejection_reason + rejection_detail
            conn.execute(
                "INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row + ("rejected", None, None)
            )
        src.close()
        print(f"Migrated {rej_db} -> {merged_db}")

    conn.close()
    print(f"Migration complete: {merged_db} created")
    print("Backup old DBs and replace with merged DB when ready")


if __name__ == "__main__":
    migrate()
