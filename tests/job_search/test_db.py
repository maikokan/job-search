import pytest
import tempfile
import sqlite3
import os
from pathlib import Path
from job_search.db import setup_database, store_job, job_id, reject_and_remove


def test_wal_mode_enabled():
    """Test that WAL journal mode is enabled on new DB connections."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        conn = setup_database(db_path)
        result = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert result == "wal", f"Expected WAL mode, got {result}"
        conn.close()


def test_jobs_sorted_by_scraped_at_desc():
    """Test that active jobs are queryable and sorted by scraped_at DESC."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        conn = setup_database(db_path)

        jobs = [
            {"title": "old", "company": "A", "location": "HK", "url": "http://old.com", "scraped_at": "2024-01-01T00:00:00"},
            {"title": "new", "company": "B", "location": "HK", "url": "http://new.com", "scraped_at": "2024-06-01T00:00:00"},
            {"title": "mid", "company": "C", "location": "HK", "url": "http://mid.com", "scraped_at": "2024-03-01T00:00:00"},
        ]
        for j in jobs:
            store_job(conn, j)

        rows = conn.execute("SELECT title FROM jobs WHERE status='active' ORDER BY scraped_at DESC").fetchall()
        assert [r[0] for r in rows] == ["new", "mid", "old"]
        conn.close()


def test_rejected_jobs_have_status_rejected():
    """Test that reject_and_remove sets status='rejected' instead of deleting."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        conn = setup_database(db_path)
        job = {"title": "test", "company": "X", "location": "HK", "url": "http://test.com", "scraped_at": "2024-01-01T00:00:00"}
        store_job(conn, job)

        reject_and_remove(conn, job, "test_reason", "test_detail")

        # Job should still exist with status='rejected'
        status = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id(job["url"]),)).fetchone()[0]
        assert status == "rejected", f"Expected status='rejected', got {status}"

        # Should also have rejection_reason and rejection_detail
        reason = conn.execute("SELECT rejection_reason FROM jobs WHERE id=?", (job_id(job["url"]),)).fetchone()[0]
        assert reason == "test_reason"

        detail = conn.execute("SELECT rejection_detail FROM jobs WHERE id=?", (job_id(job["url"]),)).fetchone()[0]
        assert detail == "test_detail"

        conn.close()


def test_status_index_exists():
    """Test that the status index is created."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        conn = setup_database(db_path)
        indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_status'").fetchall()
        assert len(indexes) == 1, "Expected idx_jobs_status index to exist"
        conn.close()


def test_scraped_at_index_exists():
    """Test that the scraped_at DESC index is created."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        conn = setup_database(db_path)
        indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_scraped_at'").fetchall()
        assert len(indexes) == 1, "Expected idx_jobs_scraped_at index to exist"
        conn.close()


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
    conn = setup_database(str(db_path))

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
    conn1 = setup_database(str(db_path))
    count1 = conn1.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", ('abc123',)).fetchone()[0]
    conn1.close()

    # Second setup (no-op migration)
    conn2 = setup_database(str(db_path))
    count2 = conn2.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", ('abc123',)).fetchone()[0]
    conn2.close()

    assert count1 == 1
    assert count2 == 1