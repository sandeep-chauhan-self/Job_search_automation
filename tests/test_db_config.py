import os
import pytest
from src.database.connection import DB_PATH
from src.database.models import Run, Job
from src.config_loader import load_config, load_profile, load_answers, load_search_filters, load_secrets

def test_db_creation(temp_db):
    assert os.path.exists(DB_PATH)

    run = Run(status="RUNNING")
    temp_db.add(run)
    temp_db.commit()

    saved_run = temp_db.query(Run).first()
    assert saved_run.status == "RUNNING"
    assert saved_run.id is not None

def test_config_loading():
    config = load_config()
    assert "llm" in config
    assert config["application"]["daily_limit"] == 25
    
    profile = load_profile()
    # Placeholder-name check mirrors src/assistant.py's is_placeholder logic.
    assert profile["personal"]["name"] not in (None, "", "John Doe")
    
    answers = load_answers()
    assert isinstance(answers, list)
    assert len(answers) > 0
    assert "pattern" in answers[0]

    filters = load_search_filters()
    assert "searches" in filters
    assert len(filters["searches"]) > 0
