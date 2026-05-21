"""Job Search CLI entry point."""
import argparse
import logging
import sys
from pathlib import Path

import yaml

from job_search.config import validate_config
from job_search.pipeline import Pipeline

logger = logging.getLogger(__name__)


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


def main():
    parser = argparse.ArgumentParser(description='Job Search — GICS Classification + Enrichment')
    parser.add_argument('--config', '-c', help='Config file path')
    parser.add_argument('--hours-old', '-t', type=int, help='Max age in hours')
    parser.add_argument('--limit', '-n', type=int, help='Results per term')
    parser.add_argument('--no-ai', action='store_true', help='Skip AI (scrape + store only)')
    parser.add_argument('--quiet', action='store_true', help='No output')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no DB writes, no notifications)')
    args = parser.parse_args()

    config = load_config(args.config)

    if args.hours_old:
        config.setdefault('search', {})['hours_old'] = args.hours_old
    if args.limit:
        config.setdefault('search', {})['results_per_term'] = args.limit

    try:
        validated = validate_config(config, args.no_ai)
    except ValueError as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)

    pipeline = Pipeline(config, validated, no_ai=args.no_ai, dry_run=args.dry_run)
    pipeline.run()


if __name__ == '__main__':
    main()

