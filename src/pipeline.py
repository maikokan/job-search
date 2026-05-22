import logging
from pathlib import Path
from typing import Dict, List

from src.config import ValidatedConfig
from src.db import (
    job_id,
    prune_old,
    reject_and_remove,
    setup_database,
    store_job,
)
from src.enrich import enrich_batch
from src.gics import classify_gics_batch, classify_gics_batch_retry
from src.scrape import filter_by_reject_words, filter_location, search_all
from src.telegram import notify_telegram

logger = logging.getLogger(__name__)


class Pipeline:
    """Job search pipeline. Each method is independently testable."""

    def __init__(self, config: dict, validated: 'ValidatedConfig', no_ai: bool = False, dry_run: bool = False):
        self.config = config
        self.validated = validated
        self.no_ai = no_ai
        self.dry_run = dry_run
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    def run(self) -> None:
        """Run full pipeline: scrape → filter → classify → enrich → notify → prune."""
        logger.info("Starting job search pipeline")

        app_dir = Path(__file__).parent.parent.parent
        db_path = app_dir / self.config.get("database", {}).get("path", "data/jobs.db")
        retention = self.config.get("database", {}).get("retention_days", 365)

        conn = setup_database(str(db_path))

        # Scrape
        terms = self.config.get("search", {}).get("terms", ["intern"])
        locations = self.config.get("search", {}).get("locations", ["Hong Kong"])
        logger.info(f"Scraping: {len(terms)} terms × {len(locations)} locations")
        jobs = search_all(terms, locations, self.config)
        logger.info(f"Fetched: {len(jobs)} jobs")

        if not jobs:
            logger.info("No jobs found")
            return

        # Dedup
        new_jobs = self._deduplicate(conn, jobs)
        logger.info(f"New: {len(new_jobs)}, dupes: {len(jobs) - len(new_jobs)}")

        if not new_jobs:
            logger.info("All jobs are duplicates")
            return

        # Filter
        new_jobs = self.filter(conn, new_jobs)
        logger.info(f"After filters: {len(new_jobs)} jobs")

        if not new_jobs:
            logger.info("No jobs after filtering")
            return

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
        logger.info(f"Matched: {len(all_matched)} jobs")

        if not all_matched:
            logger.info("No jobs to enrich")
            return

        # Enrich
        if not self.no_ai:
            self.enrich(all_matched)

        # Notify
        self.notify(all_matched)

        # Prune
        if not self.dry_run:
            logger.info(f"Pruning jobs older than {retention} days")
            prune_old(conn, retention)

        conn.close()
        logger.info("Pipeline complete")

    def _deduplicate(self, conn, jobs: List[Dict]) -> List[Dict]:
        """Remove jobs already in DB."""
        cur = conn.cursor()
        new_jobs = []
        seen_urls = set()
        for j in jobs:
            url = j.get('url', '')
            jid = job_id(url)
            if jid in seen_urls:
                continue
            seen_urls.add(jid)
            cur.execute('SELECT id FROM jobs WHERE id = ?', (jid,))
            if not cur.fetchone():
                new_jobs.append(j)
        return new_jobs

    def filter(self, conn, jobs: List[Dict]) -> List[Dict]:
        """Apply location + title reject word filters."""
        reject_words = self.validated.reject_words

        passed, loc_rejected = filter_location(jobs)
        for j in loc_rejected:
            if not self.dry_run:
                reject_and_remove(conn, j, 'location_mismatch', j.get('location', ''))

        if reject_words:
            passed, title_rejected = filter_by_reject_words(passed, reject_words)
            for j in title_rejected:
                if not self.dry_run:
                    reject_and_remove(conn, j, 'title_reject_word', j.get('_reject_word', ''))

        return passed

    def classify_and_match(self, conn, jobs: List[Dict]) -> List[Dict]:
        """Classify by GICS and filter to matched jobs."""
        desired_gics = set(self.validated.desired_gics)
        rejected_gics = set(self.validated.rejected_gics)
        ai_config = self.config.get("ai", {})

        for j in jobs:
            j['scraped_at'] = __import__('datetime').datetime.now().isoformat()

        # Classify if needed
        if not self.no_ai and desired_gics:
            logger.info(f"Classifying {len(jobs)} jobs via GICS")
            classify_gics_batch(jobs, ai_config)
            null_jobs = [j for j in jobs if not j.get('gics_code')]
            if null_jobs:
                classify_gics_batch_retry(null_jobs, ai_config)

        # Store and match
        matched = []
        for j in jobs:
            if not self.dry_run:
                store_job(conn, j)

            gics = j.get('gics_code')
            if gics is None:
                if not self.dry_run:
                    reject_and_remove(conn, j, 'gics_no_match', 'code=NULL')
            elif desired_gics and gics not in desired_gics:
                if not self.dry_run:
                    reject_and_remove(conn, j, 'gics_no_match', f'code={gics}')
            elif rejected_gics and gics in rejected_gics:
                if not self.dry_run:
                    reject_and_remove(conn, j, 'gics_rejected', f'code={gics}')
            elif desired_gics:
                if not self.dry_run:
                    reject_and_remove(conn, j, 'gics_no_match', f'code={gics}')
            else:
                matched.append(j)

        return matched

    def enrich(self, jobs: List[Dict]) -> None:
        """Enrich jobs with AI summary and fit score."""
        if self.dry_run:
            return
        logger.info(f"Enriching {len(jobs)} jobs")
        ai_config = self.config.get("ai", {})
        enrich_batch(jobs, self.config, ai_config)

        # Update DB
        app_dir = Path(__file__).parent.parent.parent
        db_path = app_dir / self.config.get("database", {}).get("path", "data/jobs.db")
        conn = setup_database(str(db_path))
        for j in jobs:
            jid = job_id(j.get('url', ''))
            conn.execute('''
                UPDATE jobs SET summary = ?, industry = ?, gics_code = ?, gics_confidence = ?,
                               fit_score = ?, enriched_at = ? WHERE id = ?
            ''', (
                j.get('summary'), j.get('industry'), j.get('gics_code'), j.get('gics_confidence'),
                j.get('fit_score'), j.get('enriched_at'), jid
            ))
        conn.commit()
        conn.close()

    def notify(self, jobs: List[Dict]) -> None:
        """Send jobs to Telegram."""
        if notify_telegram(jobs):
            app_dir = Path(__file__).parent.parent.parent
            db_path = app_dir / self.config.get("database", {}).get("path", "data/jobs.db")
            conn = setup_database(str(db_path))
            for j in jobs:
                jid = job_id(j.get('url', ''))
                conn.execute('UPDATE jobs SET notified = 1 WHERE id = ?', (jid,))
            conn.commit()
            conn.close()
            logger.info(f"Telegram: {len(jobs)} jobs sent")
