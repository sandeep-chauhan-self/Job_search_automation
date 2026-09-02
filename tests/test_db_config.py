import os
import pytest
from src.database.connection import get_db, DB_PATH
from src.database.models import Run, Job
from src.config_loader import load_config, load_profile, load_answers, load_search_filters, load_secrets

def test_db_creation():
    assert os.path.exists(DB_PATH)
    db = get_db()
    assert db is not None
    
    # Test inserts
    run = Run(status="RUNNING")
    db.add(run)
    db.commit()
    
    saved_run = db.query(Run).first()
    assert saved_run.status == "RUNNING"
    assert saved_run.id is not None
    
    db.close()

def test_config_loading():
    config = load_config()
    assert "llm" in config
    assert config["application"]["daily_limit"] == 25
    
    profile = load_profile()
    assert profile["personal"]["name"] == "John Doe"
    
    answers = load_answers()
    assert isinstance(answers, list)
    assert len(answers) > 0
    assert "pattern" in answers[0]

    filters = load_search_filters()
    assert "searches" in filters
    assert len(filters["searches"]) > 0
