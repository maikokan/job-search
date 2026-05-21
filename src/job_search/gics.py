"""GICS (Global Industry Classification Standard) reference data and classification."""
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_GICS_REFERENCE_CACHE = None


def load_gics_reference() -> str:
    """Load GICS reference from data file. Caches result."""
    global _GICS_REFERENCE_CACHE
    if _GICS_REFERENCE_CACHE is None:
        data_path = Path(__file__).parent.parent.parent / "data" / "gics_reference.csv"
        _GICS_REFERENCE_CACHE = data_path.read_text()
    return _GICS_REFERENCE_CACHE


GICS_REFERENCE = load_gics_reference()

GICS_BATCH_SYSTEM_PROMPT = f"""You are a GICS (Global Industry Classification Standard) classifier.
Classify each company into an 8-digit GICS sub-industry code from this list:

{GICS_REFERENCE}

Each entry includes a definition. Use the definitions to match accurately, not just the name.

Reply with ONLY a JSON array:
[{{"index": 0, "code": "XXXXXXXX", "sub_industry": "Name", "confidence": 0.95}}, ...]

Rules:
- One object per company, in order by index
- Read the definitions carefully to distinguish between similar sub-industries
- If unknown: {{"index": N, "code": "UNKNOWN", "sub_industry": "", "confidence": 0.0}}"""


def _sanitize(text: str) -> str:
    """Clean text for LLM input."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'[ \t]{4,}', '  ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def llm_call(system: str, user: str, model: str, api_key: str, endpoint: str, max_tokens: int = 500, retries: int = 2) -> str:
    """Generic LLM call via OmniRoute. Returns response text."""
    system = _sanitize(system)
    user = _sanitize(user)

    data = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
    }).encode()

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()

            if raw.startswith(b'data:'):
                content_parts = []
                for line in raw.decode('utf-8').splitlines():
                    if line.startswith('data: '):
                        payload = line[6:]
                        if payload.strip() == '[DONE]':
                            continue
                        try:
                            chunk = json.loads(payload)
                            delta = (((chunk.get('choices') or [{}])[0].get('delta', {}) or {}).get('content') or '')
                            if delta:
                                content_parts.append(delta)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                return ''.join(content_parts).strip()

            result = json.loads(raw)
            content = (((result.get("choices") or [{}])[0].get("message", {}) or {}).get("content") or "").strip()
            return content
        except (urllib.error.URLError, urllib.request.HTTPError, TimeoutError, ValueError) as e:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.error(f"LLM error after {retries + 1} attempts: {e}")
            return ""
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return ""

    return ""  # safety return (should never reach here)


def _parse_gics_response(response: str) -> Dict:
    """Parse GICS JSON/plain text response."""
    result = {"code": None, "sub_industry": "", "confidence": 0.0}
    if not response:
        return result

    try:
        match = re.search(r'\{[^}]+\}', response)
        if match:
            parsed = json.loads(match.group(0))
            code_str = str(parsed.get("code", ""))
            if re.match(r'\d{8}', code_str):
                result["code"] = int(code_str)
                result["sub_industry"] = parsed.get("sub_industry", parsed.get("industry", ""))
                result["confidence"] = float(parsed.get("confidence", 0.0))
                return result
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    code_match = re.search(r'(\d{8})', response)
    if code_match:
        result["code"] = int(code_match.group(1))
        result["confidence"] = 0.5
        remainder = response[code_match.end():].strip().lstrip(':').lstrip('-').strip()
        remainder = re.sub(r'\s*\{.*', '', remainder).strip()
        if remainder and len(remainder) > 2:
            result["sub_industry"] = remainder[:100]

    return result


def classify_gics(company: str, title: str = "", description: str = "", ai_config: Dict | None = None) -> Dict:
    """Classify company to 8-digit GICS code with confidence."""
    if ai_config is None:
        ai_config = {}
    result = {"code": None, "sub_industry": "", "confidence": 0.0}

    company = _sanitize(company)
    title = _sanitize(title)
    description = re.sub(r'<[^>]+>', '', _sanitize(description))

    if not company:
        return result

    model = ai_config.get('model', '')
    api_key = ai_config.get('api_key', '')
    endpoint = ai_config.get('endpoint', 'http://localhost:20128/v1/chat/completions')

    system = f"""You are a GICS (Global Industry Classification Standard) classifier.
Given a company name and optionally a job title and description, classify it into an 8-digit GICS sub-industry code from this list:

{GICS_REFERENCE}

Each entry includes a definition. Use the definitions to match accurately, not just the name.

Reply in this EXACT format (JSON):
{{"code": "XXXXXXXX", "sub_industry": "Sub-Industry Name", "confidence": 0.00}}

Rules:
- code: the 8-digit GICS code (e.g., "40101010")
- sub_industry: the sub-industry name from the list
- confidence: your confidence 0.00-1.00 (0.00 = guessing, 1.00 = certain)
- If you cannot determine the code, use {{"code": "UNKNOWN", "sub_industry": "", "confidence": 0.00}}."""

    # Attempt 1: company + title
    user_input = f"Company: {company}"
    if title:
        user_input += f"\nJob Title: {title}"
    response = llm_call(system, user_input, model, api_key, endpoint)
    result = _parse_gics_response(response)

    if result["code"] is not None:
        return result

    # Attempt 2: add description
    if description:
        user_input_2 = f"Company: {company}"
        if title:
            user_input_2 += f"\nJob Title: {title}"
        user_input_2 += f"\nJob Description: {description}"
        response = llm_call(system, user_input_2, model, api_key, endpoint)
        result2 = _parse_gics_response(response)
        if result2["code"] is not None:
            return result2

    return result


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


def classify_gics_batch_retry(jobs: List[Dict], ai_config: Dict) -> None:
    """Retry GICS classification for NULL jobs with full description in batches. Modifies jobs in-place."""
    if not jobs:
        return

    batch_size = ai_config.get('classify_batch_size', 5)

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
            title = _sanitize(j.get('title', ''))
            desc = j.get('description') or ''
            desc_clean = re.sub(r'<[^>]+>', '', desc)
            items.append(f"{len(items)}. Company: {company} | Title: {title} | Description: {desc_clean}")

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
        prompt = "Companies to classify (retry with full description):\n" + numbered + "\n"

        response = llm_call(
            GICS_BATCH_SYSTEM_PROMPT,
            prompt,
            model,
            api_key,
            endpoint,
            max_tokens=len(batch_items) * 200,
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
