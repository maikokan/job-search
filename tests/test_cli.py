# tests/job_search/test_cli.py
import pytest
import tempfile
import os
import shutil
from pathlib import Path
from src.cli import load_config

def test_load_config_from_project_root(tmp_path, monkeypatch):
    """Config loaded from project root config.yaml."""
    # Write config to actual project root (app_dir derived from __file__ points there)
    project_root = Path('/opt/job-search')
    config_file = project_root / 'config.yaml'

    # Backup existing config if present
    backup = None
    if config_file.exists():
        backup = config_file.read_text()

    try:
        config_content = {
            'search': {'terms': ['foo']},
            'ai': {'classify_batch_size': 7},
        }
        import yaml
        config_file.write_text(yaml.dump(config_content))

        cfg = load_config()
        assert cfg['search']['terms'] == ['foo']
        assert cfg['ai']['classify_batch_size'] == 7
    finally:
        # Restore backup or remove test config
        if backup is not None:
            config_file.write_text(backup)
        elif config_file.exists():
            config_file.unlink()