import pytest
from unittest.mock import patch, MagicMock
from job_search.gics import classify_gics_batch


def test_batches_of_n(monkeypatch):
    """Jobs are classified in batches of ai.classify_batch_size."""
    mock_response = '[{"index":0,"code":"40101010","sub_industry":"Banks","confidence":0.9}]'
    call_count = [0]

    def mock_llm(*args, **kwargs):
        call_count[0] += 1
        return mock_response

    monkeypatch.setattr('job_search.gics.llm_call', mock_llm)

    jobs = [
        {'company': f'Company{i}', 'title': 'Analyst', 'description': 'desc'}
        for i in range(12)
    ]
    ai_config = {'model': 'gpt-4', 'api_key': '', 'endpoint': 'http://x', 'classify_batch_size': 5}

    classify_gics_batch(jobs, ai_config)

    # 12 jobs, batch_size=5 → ceil(12/5) = 3 batches
    assert call_count[0] == 3