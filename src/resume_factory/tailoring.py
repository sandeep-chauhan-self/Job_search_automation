import yaml
import json
from src.llm.client import LLMClient

TAILOR_SYSTEM = """You are an expert resume writer specializing in ATS-optimized resumes. You rewrite resume content to maximize relevance for specific job descriptions.

CRITICAL RULES:
1. ONLY use facts from the provided candidate profile. Do NOT fabricate metrics, employers, certifications, skills, or achievements.
2. If the candidate lacks a skill the job requires, OMIT it. Do NOT invent experience.
3. Reorder and rephrase existing bullet points to highlight relevance to THIS specific job.
4. Inject exact keywords from the job description into bullet points where the candidate genuinely has that experience.
5. Use strong action verbs.
6. Keep bullet points concise (1 line each, max 15 words).
7. Write a tailored professional summary (2-3 sentences) that positions the candidate for THIS specific role.
8. Return ONLY valid JSON. No markdown, no explanation outside the JSON."""

TAILOR_USER = """## Candidate Profile
{profile_yaml}

## Target Job
Title: {job_title}
Company: {company}
Description:
{job_description}

## Match Analysis
Strengths: {reasons}
Gaps: {gaps}

## Task
Rewrite this candidate's resume content to be maximally relevant for the target job.
Return JSON in exactly this format:
{{
  "summary": "Tailored 2-3 sentence professional summary",
  "experience": [
    {{
      "title": "Exact title from profile",
      "company": "Exact company from profile",
      "location": "Exact location from profile",
      "dates": "Month Year - Month Year",
      "bullets": ["Tailored bullet 1", "Tailored bullet 2", "Tailored bullet 3"]
    }}
  ],
  "skills": {{
    "languages": ["..."],
    "frameworks": ["..."],
    "tools": ["..."]
  }}
}}

IMPORTANT: Keep ALL experience entries from the profile. Only rewrite bullets and reorder skills. Do NOT remove or add employers."""

COVER_LETTER_SYSTEM = """You are a professional cover letter writer. Write concise, genuine cover letters.

RULES:
1. ONLY use facts from the candidate's profile. Do NOT fabricate.
2. 3 paragraphs max: (1) Why interested, (2) Most relevant experience, (3) Closing.
3. Keep it under 250 words.
4. Sound human, not robotic.
5. Return plain text only. No markdown, no JSON."""

COVER_LETTER_USER = """## Candidate Profile
{profile_yaml}

## Target Job
Title: {job_title}
Company: {company}
Description:
{short_desc}

## Task
Write a cover letter for this candidate applying to this role. 3 paragraphs, under 250 words."""

class ResumeTailor:
    def __init__(self, llm_client: LLMClient, profile: dict):
        self.llm = llm_client
        self.profile = profile
        self.profile_yaml = yaml.dump(profile, sort_keys=False)

    def tailor_for_job(self, job: dict, job_id: str, run_id: str) -> dict:
        user_prompt = TAILOR_USER.format(
            profile_yaml=self.profile_yaml,
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", ""),
            reasons=job.get("match_reasons", "[]"),
            gaps=job.get("match_gaps", "[]")
        )
        
        response = self.llm.complete(
            prompt=user_prompt,
            system_prompt=TAILOR_SYSTEM,
            response_format="json",
            purpose="tailoring_resume",
            job_id=job_id,
            run_id=run_id
        )
        
        # Merge basic info
        merged = {
            "name": self.profile.get("personal", {}).get("name", ""),
            "email": self.profile.get("personal", {}).get("email", ""),
            "phone": self.profile.get("personal", {}).get("phone", ""),
            "location": self.profile.get("personal", {}).get("location", ""),
            "linkedin_url": self.profile.get("personal", {}).get("linkedin_url", ""),
            "github_url": self.profile.get("personal", {}).get("github_url", ""),
            "portfolio_url": self.profile.get("personal", {}).get("portfolio_url", ""),
            "education": self.profile.get("education", [])
        }
        if isinstance(response, dict):
            merged.update(response)
        return merged

    def should_generate_cover_letter(self, job_description: str) -> bool:
        if not job_description:
            return False
        return "cover letter" in job_description.lower()

    def generate_cover_letter(self, job: dict, job_id: str, run_id: str) -> str:
        desc = job.get("description", "")
        short_desc = desc[:1000] if desc else ""
        
        user_prompt = COVER_LETTER_USER.format(
            profile_yaml=self.profile_yaml,
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            short_desc=short_desc
        )
        
        response = self.llm.complete(
            prompt=user_prompt,
            system_prompt=COVER_LETTER_SYSTEM,
            response_format="text",
            purpose="tailoring_cover_letter",
            job_id=job_id,
            run_id=run_id
        )
        return str(response)
