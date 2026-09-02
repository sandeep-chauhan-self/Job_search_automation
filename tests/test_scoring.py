import pytest
import json
from src.scoring.engine import ScoringEngine
from src.database.connection import get_db
from src.database.models import Job

class MockLLMClient:
    def __init__(self, responses=None):
        self.responses = responses or []
        
    def complete(self, **kwargs):
        from src.llm.client import LLMResponseError
        if not self.responses:
            raise LLMResponseError("Mock error")
            
        res = self.responses.pop(0)
        if isinstance(res, Exception):
            raise res
        return res

def test_prompt_building():
    db = get_db()
    profile = {"personal": {"name": "Test"}}
    engine = ScoringEngine(db, None, {}, profile)
    
    job = Job(title="Dev", company="Tech", description="We need a dev.")
    sys_p, user_p = engine._build_prompt(job)
    
    assert "You are a career match scoring engine" in sys_p
    assert "name: Test" in user_p
    assert "Title: Dev" in user_p
    assert "We need a dev." in user_p

def test_scoring_run():
    db = get_db()
    
    # Add test jobs
    run_id = "test-run"
    job1 = Job(title="Good Job", company="Tech", description="A long enough desc.", status="DISCOVERED", run_id=run_id, dedup_hash="1", platform="linkedin", job_url="http")
    job2 = Job(title="Bad Job", company="Tech", description="A long enough desc.", status="DISCOVERED", run_id=run_id, dedup_hash="2", platform="linkedin", job_url="http")
    job3 = Job(title="Empty Job", company="Tech", description="Short", status="DISCOVERED", run_id=run_id, dedup_hash="3", platform="linkedin", job_url="http")
    
    db.add_all([job1, job2, job3])
    db.commit()
    
    mock_llm = MockLLMClient(responses=[
        {"score": 85, "reasons": ["Good"], "gaps": []},  # For job1 -> SCORED
        {"score": 40, "reasons": [], "gaps": ["Bad"]}    # For job2 -> SKIPPED
    ])
    
    config = {"application": {"min_match_score": 60}}
    engine = ScoringEngine(db, mock_llm, config, {})
    
    stats = engine.run(run_id)
    
    assert stats["scored"] == 2
    assert stats["skipped"] == 1 # job3
    assert stats["above_threshold"] == 1 # job1
    
    # Check DB updates
    db.refresh(job1)
    db.refresh(job2)
    db.refresh(job3)
    
    assert job1.status == "SCORED"
    assert job1.match_score == 85
    assert "Good" in job1.match_reasons
    
    assert job2.status == "SKIPPED"
    assert job2.match_score == 40
    
    assert job3.status == "SKIPPED"
    assert job3.match_score is None # Never called LLM
    
    # Cleanup
    db.delete(job1)
    db.delete(job2)
    db.delete(job3)
    db.commit()
