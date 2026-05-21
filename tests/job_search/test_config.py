import pytest
from job_search.config import validate_config, ValidatedConfig

def test_empty_desired_gics_no_ai_allowed():
    """No desired_gics, no AI — should pass (no filtering)."""
    cfg = validate_config({"desired_gics": [], "ai": {"endpoint": ""}}, no_ai=False)
    assert cfg.desired_gics == []

def test_empty_desired_gics_with_ai_ok():
    """No desired_gics but AI configured — should pass."""
    cfg = validate_config({"desired_gics": [], "ai": {"endpoint": "http://localhost:20128"}}, no_ai=False)
    assert cfg.ai_endpoint == "http://localhost:20128"

def test_desired_gics_with_no_ai_skips_validation():
    """desired_gics set, --no-ai flag, no AI config — should pass (GICS filter skipped)."""
    cfg = validate_config({"desired_gics": ["40101010"], "ai": {"endpoint": ""}}, no_ai=True)
    assert cfg.no_ai == True
    assert cfg.desired_gics == [40101010]

def test_desired_gics_with_empty_ai_raises():
    """desired_gics set, no --no-ai flag, no AI config — should error."""
    with pytest.raises(ValueError, match="ai.endpoint is empty"):
        validate_config({"desired_gics": ["40101010"], "ai": {"endpoint": ""}}, no_ai=False)

def test_desired_gics_with_ai_endpoint_ok():
    """desired_gics set, AI endpoint configured — should pass."""
    cfg = validate_config({"desired_gics": ["40101010"], "ai": {"endpoint": "http://localhost:20128"}}, no_ai=False)
    assert cfg.desired_gics == [40101010]
    assert cfg.ai_endpoint == "http://localhost:20128"

def test_rejected_gics_extracted():
    """rejected_gics should be parsed as integers."""
    cfg = validate_config({"rejected_gics": ["40301020", "40301010"]}, no_ai=True)
    assert cfg.rejected_gics == [40301020, 40301010]

def test_reject_words_preserved():
    """reject_words should be passed through."""
    cfg = validate_config({"reject_words": ["Senior", "Lead"]}, no_ai=True)
    assert cfg.reject_words == ["Senior", "Lead"]

def test_empty_reject_words():
    """Empty reject_words is valid."""
    cfg = validate_config({"reject_words": []}, no_ai=True)
    assert cfg.reject_words == []