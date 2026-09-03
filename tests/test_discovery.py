import pytest
import pandas as pd
from src.discovery.engine import DiscoveryEngine
from src.database.models import Job

def test_dedup_hash():
    engine = DiscoveryEngine(None, {}, {}, {})
    hash1 = engine._compute_dedup_hash("TechCorp", "Software Engineer", "Bangalore")
    hash2 = engine._compute_dedup_hash("  techcorp ", "software ENGINEER", "bangalore  ")
    assert hash1 == hash2
    
    hash3 = engine._compute_dedup_hash("OtherCorp", "Software Engineer", "Bangalore")
    assert hash1 != hash3

def test_blacklist():
    profile = {"preferences": {"companies_blacklist": ["SpamCorp", "BadInc"]}}
    engine = DiscoveryEngine(None, {}, {}, profile)
    assert engine._is_blacklisted("spamcorp")
    assert engine._is_blacklisted("SpamCorp")
    assert engine._is_blacklisted("badinc")
    assert not engine._is_blacklisted("GoodCorp")

def test_exclude_keywords():
    filters = {"exclude_keywords": ["intern", "unpaid"]}
    engine = DiscoveryEngine(None, {}, filters, {})
    
    assert engine._matches_exclude_keywords("Software Engineer Intern", "", ["intern"])
    assert engine._matches_exclude_keywords("Software Engineer", "This is an unpaid role.", ["unpaid"])
    assert not engine._matches_exclude_keywords("Senior Software Engineer", "Great pay", ["intern"])

def test_discovery_run(monkeypatch, temp_db):
    db = temp_db
    
    config = {"platforms": {"linkedin": True}}
    filters = {"searches": [{"title": "Dev", "location": "Remote"}], "exclude_keywords": ["intern"]}
    profile = {"preferences": {"companies_blacklist": ["SpamCorp"]}}
    
    engine = DiscoveryEngine(db, config, filters, profile)
    
    def mock_scrape_jobs(*args, **kwargs):
        return pd.DataFrame({
            "title": ["Dev", "Intern Dev", "Dev"],
            "company": ["GoodCorp", "GoodCorp", "SpamCorp"],
            "location": ["Remote", "Remote", "Remote"],
            "site": ["linkedin", "linkedin", "linkedin"],
            "job_url": ["url1", "url2", "url3"],
            "description": ["desc1", "desc2", "desc3"],
            "is_remote": [True, True, True],
            "min_amount": [None, None, None],
            "max_amount": [None, None, None],
            "interval": [None, None, None]
        })
        
    monkeypatch.setattr("src.discovery.engine.scrape_jobs", mock_scrape_jobs)
    
    # Should only insert the first job. Second is 'intern', third is 'SpamCorp'.
    jobs_discovered = engine.run("run-123")
    assert jobs_discovered == 1
    
    # Run again, should discover 0 because of dedup
    jobs_discovered_again = engine.run("run-123")
    assert jobs_discovered_again == 0
