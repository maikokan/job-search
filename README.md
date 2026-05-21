# Job Search

Job scraping with GICS classification, AI enrichment, and Telegram notifications.

## Usage

```bash
uv run job-search --help
uv run job-search --hours-old 48
uv run job-search --no-ai
```

## Configuration

Edit `config/config.yaml` to customize search terms, locations, GICS codes, etc.

## Cron Setup

```bash
0 */4 * * * cd /opt/job-search && uv run job-search >> /var/log/job-search.log 2>&1
```