from unittest.mock import MagicMock

from src.pipeline import Pipeline


def test_no_ai_skips_gics_and_enrich(monkeypatch):
    """--no-ai skips classify and enrich entirely."""
    classify_called = [False]
    enrich_called = [False]
    monkeypatch.setattr('src.pipeline.classify_gics_batch', lambda *a, **k: classify_called.__setitem__(0, True))
    monkeypatch.setattr('src.pipeline.classify_gics_batch_retry', lambda *a, **k: classify_called.__setitem__(0, True))
    monkeypatch.setattr('src.pipeline.enrich_batch', lambda *a, **k: enrich_called.__setitem__(0, True))
    monkeypatch.setattr('src.pipeline.notify_telegram', lambda *a, **k: True)

    config = {
        'search': {'terms': [], 'locations': []},
        'ai': {'classify_batch_size': 5, 'enrich_batch_size': 5},
        'database': {'path': ':memory:'}
    }
    validated = MagicMock(desired_gics=[], rejected_gics=[], reject_words=[], no_ai=True)
    pipe = Pipeline(config, validated, no_ai=True, dry_run=False)
    pipe.run()

    assert not classify_called[0], "GICS should be skipped with --no-ai"
    assert not enrich_called[0], "Enrich should be skipped with --no-ai"

def test_dry_run_skips_db_writes(monkeypatch):
    """--dry-run runs full pipeline but skips DB writes."""
    store_called = [False]
    reject_called = [False]
    monkeypatch.setattr('src.pipeline.store_job', lambda *a, **k: store_called.__setitem__(0, True))
    monkeypatch.setattr('src.pipeline.reject_and_remove', lambda *a, **k: reject_called.__setitem__(0, True))
    monkeypatch.setattr('src.pipeline.notify_telegram', lambda *a, **k: True)

    config = {
        'search': {'terms': [], 'locations': []},
        'ai': {'classify_batch_size': 5, 'enrich_batch_size': 5},
        'database': {'path': ':memory:'}
    }
    validated = MagicMock(desired_gics=[], rejected_gics=[], reject_words=[], no_ai=False)
    pipe = Pipeline(config, validated, no_ai=False, dry_run=True)
    pipe.run()

    assert not store_called[0], "store_job should be skipped with --dry-run"
    assert not reject_called[0], "reject_and_remove should be skipped with --dry-run"
