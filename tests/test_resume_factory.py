import pytest
import os
from src.resume_factory.tailoring import ResumeTailor
from src.resume_factory.renderer import ResumeRenderer

SAMPLE_PROFILE = {
    "personal": {"name": "Test Name", "email": "t@example.com"},
    "headline": "Python Developer | Reliability",
    "summary": "Base summary.",
    "impact_snapshot": ["Impact one", "Impact two", "Impact three"],
    "experience": [
        {
            "title": "Senior Dev",
            "company": "Alpha",
            "location": "Bengaluru",
            "dates": "2024 - Present",
            "bullets": ["A one", "A two", "A three"],
        },
        {
            "title": "Dev",
            "company": "Beta",
            "location": "Pune",
            "start_date": "2022-06",
            "end_date": "2023-06",
            "bullets": ["B one", "B two"],
        },
    ],
    "projects": [
        {"name": "Proj", "tech_stack": "Python, Flask", "bullets": ["P one", "P two"]},
    ],
    "skills": {"Languages & Platforms": ["Python", "SQL", "JavaScript"]},
    "education": [{"degree": "B.Tech", "institution": "AKTU", "year": 2022}],
    "certifications": ["Cert A", "Cert B"],
}

JOB = {"title": "Dev", "company": "Tech", "description": ""}


class MockLLMClient:
    def complete(self, response_format="json", **kwargs):
        if response_format == "json":
            return {
                "summary": "Mock summary",
                "experience": [],
                "skills": {"tools": ["MockTool"]}
            }
        return "Mock cover letter body"


class LossyLLMClient:
    """Drops a role, most bullets, the headline, projects and a skill; invents one skill."""

    def complete(self, response_format="json", **kwargs):
        if response_format == "json":
            return {
                "summary": "Tailored summary",
                "experience": [
                    {"company": "Alpha", "title": "Senior Dev", "bullets": ["Only one"]}
                ],
                "skills": {"Languages & Platforms": ["SQL", "Fabricated", "Python"]},
            }
        return "Mock cover letter body"


class BrokenLLMClient:
    def complete(self, response_format="json", **kwargs):
        return "not json at all"


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


def test_dropped_content_is_restored_from_profile():
    res = ResumeTailor(LossyLLMClient(), SAMPLE_PROFILE).tailor_for_job(JOB, "job-1", "run-1")

    assert res["summary"] == "Tailored summary"
    assert res["headline"] == "Python Developer | Reliability"
    assert res["impact_snapshot"] == ["Impact one", "Impact two", "Impact three"]

    assert len(res["experience"]) == 2
    assert res["experience"][0]["bullets"] == ["A one", "A two", "A three"]
    assert res["experience"][1]["company"] == "Beta"
    assert res["experience"][1]["bullets"] == ["B one", "B two"]
    assert res["experience"][1]["dates"] == "2022-06 - 2023-06"

    assert len(res["projects"]) == 1
    assert res["projects"][0]["tech_stack"] == "Python, Flask"
    assert res["projects"][0]["bullets"] == ["P one", "P two"]

    assert res["certifications"] == ["Cert A", "Cert B"]
    assert res["education"] == SAMPLE_PROFILE["education"]


def test_skills_are_reordered_but_never_lost_or_invented():
    res = ResumeTailor(LossyLLMClient(), SAMPLE_PROFILE).tailor_for_job(JOB, "job-1", "run-1")

    assert res["skills"] == {"Languages & Platforms": ["SQL", "Python", "JavaScript"]}


def test_non_dict_response_falls_back_to_full_profile():
    res = ResumeTailor(BrokenLLMClient(), SAMPLE_PROFILE).tailor_for_job(JOB, "job-1", "run-1")

    assert res["summary"] == "Base summary."
    assert res["experience"][0]["bullets"] == ["A one", "A two", "A three"]
    assert res["skills"]["Languages & Platforms"] == ["Python", "SQL", "JavaScript"]


def test_prompt_declares_required_bullet_counts():
    spec = ResumeTailor(MockLLMClient(), SAMPLE_PROFILE)._shape_spec()

    assert '"Senior Dev" at "Alpha" -> exactly 3 bullets' in spec
    assert "impact_snapshot: exactly 3 bullets" in spec
    assert '"Languages & Platforms" -> exactly 3 items' in spec


def test_template_renders_every_section():
    content = ResumeTailor(LossyLLMClient(), SAMPLE_PROFILE).tailor_for_job(JOB, "job-1", "run-1")
    renderer = ResumeRenderer()

    html = renderer._build_resume_html(content, include_education=True)
    for heading in ("Professional Summary", "Impact Snapshot", "Work Experience",
                    "Selected Projects", "Technical Skills", "Certifications", "Education"):
        assert heading in html
    assert "A three" in html
    assert "P two" in html
    assert "Cert B" in html
    assert "Languages &amp; Platforms" in html

    assert "AKTU" not in renderer._build_resume_html(content, include_education=False)


@pytest.mark.asyncio
async def test_rendering():
    # Make sure we run in root path or paths exist
    os.makedirs("output/resumes", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    
    renderer = ResumeRenderer()
    assert renderer._slugify("Tech Corp, Inc.") == "tech_corp_inc"
