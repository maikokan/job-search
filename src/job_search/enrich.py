"""AI enrichment for jobs — summary, fit score, role relevance."""
import datetime
import json
import logging
import re
from typing import Dict, List

from job_search.gics import llm_call

logger = logging.getLogger(__name__)


def check_role_relevance(title: str, description: str, ai_config: Dict) -> bool:
    """Check if a job role is relevant to finance/investment/consulting careers."""
    if not title:
        return True

    model = ai_config.get('model', '')
    api_key = ai_config.get('api_key', '')
    endpoint = ai_config.get('endpoint', 'http://localhost:20128/v1/chat/completions')

    desc = description or ""
    prompt = f"Job Title: {title}\nDescription: {desc}"
    response = llm_call(
        "Is this job role directly relevant to finance, investment, banking, "
        "consulting, asset management, real estate, risk, compliance, or quantitative analysis careers? "
        "Reply with ONLY 'yes' or 'no'. "
        "Say 'no' for: customer support, IT/engineering, marketing, HR/recruiting, "
        "operations, facilities, administrative, legal, and other non-finance roles — "
        "even if the company is in finance. Judge the ROLE, not the company.",
        prompt,
        model,
        api_key,
        endpoint,
        max_tokens=10,
    )
    return response.strip().lower().startswith("y") if response else True


def enrich_batch(jobs: List[Dict], config: dict, ai_config: Dict) -> None:
    """Enrich all matched jobs in batches. Modifies jobs in-place."""
    if not jobs:
        return

    reject_words = config.get('reject_words', [])

    # Filter out reject words first
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

    batch_size = ai_config.get('enrich_batch_size', 5)

    model = ai_config.get('model', '')
    api_key = ai_config.get('api_key', '')
    endpoint = ai_config.get('endpoint', 'http://localhost:20128/v1/chat/completions')

    results = {}
    for batch_start in range(0, len(eligible), batch_size):
        batch_eligible = eligible[batch_start:batch_start + batch_size]

        # Build batch prompt
        items = []
        for i, j in enumerate(batch_eligible):
            title = j.get('title') or ''
            company = j.get('company') or ''
            desc = j.get('description') or ''
            items.append(f"[{i}] {company} | {title}\n{desc}")

        numbered = "\n---\n".join(items)

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
            max_tokens=min(8000, len(batch_eligible) * 300),
            retries=2,
        )

        # Offset indices by batch_start
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
