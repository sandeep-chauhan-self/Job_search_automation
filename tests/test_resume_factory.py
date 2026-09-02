import pytest
import os
from src.resume_factory.tailoring import ResumeTailor
from src.resume_factory.renderer import ResumeRenderer

class MockLLMClient:
    def complete(self, response_format="json", **kwargs):
        if response_format == "json":
            return {
                "summary": "Mock summary",
                "experience": [],
                "skills": {"tools": ["MockTool"]}
            }
        return "Mock cover letter body"

def test_tailoring():
    profile = {"personal": {"name": "Test Name"}, "education": []}
    tailor = ResumeTailor(MockLLMClient(), profile)
    
    res = tailor.tailor_for_job({"title": "Dev", "company": "Tech", "description": ""}, "job-1", "run-1")
    assert res["name"] == "Test Name"
    assert res["summary"] == "Mock summary"
    
    assert tailor.should_generate_cover_letter("Please attach a cover letter") is True
    assert tailor.should_generate_cover_letter("No cover req") is False
    
    cl = tailor.generate_cover_letter({"title": "Dev"}, "job-1", "run-1")
    assert cl == "Mock cover letter body"

@pytest.mark.asyncio
async def test_rendering():
    # Make sure we run in root path or paths exist
    os.makedirs("output/resumes", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    
    renderer = ResumeRenderer()
    assert renderer._slugify("Tech Corp, Inc.") == "tech_corp_inc"
