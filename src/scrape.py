"""Job scraping via JobSpy."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from jobspy import Site, scrape_jobs

logger = logging.getLogger(__name__)


def resolve_sites(site_names: List[str]) -> List[Site]:
    """Convert string names to JobSpy Site enums."""
    sites = []
    for name in site_names:
        try:
            sites.append(Site[name.upper()])
        except KeyError:
            logger.warning(f"Warning: unknown site '{name}', skipping")
    return sites or [Site.LINKEDIN]


def search_single(query: str, location: str, config: dict) -> List[Dict]:
    """Run one JobSpy search. Returns list of job dicts."""
    scrapers = config.get('scrapers', {})
    search = config.get('search', {})
    sites = resolve_sites(scrapers.get('sites', ['linkedin']))

    logger.info(f"  '{query}' in {location} ({', '.join(s.name.lower() for s in sites)})")

    try:
        df = scrape_jobs(
            site_name=sites,
            search_term=query,
            location=location,
            results_wanted=search.get('results_per_term', 50),
            hours_old=search.get('hours_old', 24),
            is_remote=search.get('is_remote', False),
            radius=search.get('radius', 50),
            linkedin_fetch_description=scrapers.get('linkedin_fetch_description', True),
            proxies=scrapers.get('proxies'),
            verbose=0,
        )
        if df.empty:
            return []

        jobs = []
        for _, row in df.iterrows():
            # Fix "today" location → Remote
            location = row.get('location', '')
            if location and location.lower() == 'today':
                location = 'Remote'

            jobs.append({
                'title': row.get('title', ''),
                'company': row.get('company', ''),
                'location': location,
                'url': row.get('job_url', ''),
                'job_type': row.get('job_type'),
                'is_remote': bool(row.get('is_remote', False)),
                'description': row.get('description'),
            })
        return jobs

    except Exception as e:
        logger.error(f"  Error: {e}")
        return []


def search_all(terms: List[str], locations: List[str], config: dict) -> List[Dict]:
    """Search all terms × locations in parallel. Returns all jobs."""
    tasks = [(term, loc) for loc in locations for term in terms]
    all_jobs = []
    max_workers = config.get('scrapers', {}).get('max_workers', 8)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(search_single, term, loc, config): (term, loc) for term, loc in tasks}
        for future in as_completed(futures):
            term, loc = futures[future]
            try:
                jobs = future.result()
                logger.debug(f"    → {term!r} in {loc}: {len(jobs)} results")
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"    → {term!r} in {loc}: ERROR {e}")

    return all_jobs


def filter_by_reject_words(jobs: List[Dict], reject_words: list) -> tuple[List[Dict], List[Dict]]:
    """Split jobs into kept and rejected based on title reject words."""
    if not reject_words:
        return jobs, []
    kept, rejected = [], []
    for j in jobs:
        title = j.get('title', '')
        matched_word = None
        for word in reject_words:
            pattern = r'\b' + re.escape(word.lower()) + r'\b'
            if re.search(pattern, title.lower()):
                matched_word = word
                break
        if matched_word:
            j['_reject_word'] = matched_word
            rejected.append(j)
        else:
            kept.append(j)
    return kept, rejected


def filter_location(jobs: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """Filter jobs by location. Reject Guangdong (appears in HK searches)."""
    passed, rejected = [], []
    for j in jobs:
        loc = j.get('location') or ''
        if 'Guangdong' in loc:
            rejected.append(j)
        else:
            passed.append(j)
    return passed, rejected
