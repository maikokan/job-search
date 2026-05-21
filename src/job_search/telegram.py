"""Telegram notifications for matched jobs."""
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


def load_telegram_creds() -> tuple[str, str]:
    """Read bot token and chat ID from config or environment."""
    # Try reading from .env in the app directory first
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        env = {}
        for line in env_path.read_text().splitlines():
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        token = env.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = env.get('TELEGRAM_CRON_CHANNEL', '')
        if token and chat_id:
            return token, chat_id

    # Fallback to home directory
    home_env = Path.home() / '.hermes' / '.env'
    if home_env.exists():
        env = {}
        for line in home_env.read_text().splitlines():
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        return env.get('TELEGRAM_BOT_TOKEN', ''), env.get('TELEGRAM_CRON_CHANNEL', '')

    return '', ''


def clean_desc(text: str) -> str:
    """Strip markdown/HTML, truncate."""
    if not text:
        return ""
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\\t', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 250:
        text = text[:250].rsplit(' ', 1)[0] + "..."
    return text


def format_job_message(job: Dict) -> str:
    """Build a single job's Telegram message."""
    company = job.get('company', 'Unknown')
    title = job.get('title', 'Unknown')
    location = job.get('location', '')
    desc = job.get('summary') or clean_desc(job.get('description', ''))
    url = job.get('url', '')

    lines = [f"<b>{company}</b>"]
    lines.append(f"{title} | {location}" if location else title)
    lines.extend(["", desc, "", url, ""])
    return "\n".join(lines)


def split_into_batches(messages: List[str], limit: int = 4000) -> List[str]:
    """Split messages into batches under limit."""
    batches = []
    current = ""
    for msg in messages:
        if len(msg) > limit:
            cutoff = msg[:limit].rfind('. ')
            if cutoff < int(limit * 0.85):
                cutoff = msg[:limit].rfind(' ')
            if cutoff < 100:
                cutoff = limit
            batches.append(msg[:cutoff].rstrip() + "...")
            batches.append("[cont.] " + msg[cutoff:].lstrip())
        elif len(current) + len(msg) + 1 > limit:
            batches.append(current.rstrip())
            current = msg + "\n"
        else:
            current += msg + "\n"
    if current.strip():
        batches.append(current.strip())
    return batches


def notify_telegram(enriched_jobs: List[Dict]) -> bool:
    """Send enriched jobs to Telegram. Returns True on success."""
    token, chat_id = load_telegram_creds()
    if not token or not chat_id:
        logger.warning("Telegram: missing credentials")
        return False

    if not enriched_jobs:
        return True

    msgs = [format_job_message(j) for j in enriched_jobs]
    batches = split_into_batches(msgs)

    for i, batch in enumerate(batches):
        msg = batch
        if len(batches) > 1:
            msg += f"\n(Part {i+1}/{len(batches)})"

        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=data, method="POST"
                )
                urllib.request.urlopen(req, timeout=15)
                break
            except urllib.request.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                logger.error(f"Telegram error: {e}")
                return False
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                logger.error(f"Telegram error: {e}")
                return False

    return True
