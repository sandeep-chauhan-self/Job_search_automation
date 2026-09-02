import logging
import yaml
from datetime import datetime
from sqlalchemy.orm import Session
from src.database.models import Job, Run
from src.llm.client import LLMClient, LLMResponseError
import json

SYSTEM_PROMPT = """You are a career match scoring engine. You analyze job descriptions against a candidate's profile and provide a match score.

Rules:
- Score from 0 to 100 based on how well the candidate's experience matches the job requirements.
- Be realistic. A 90+ score means the candidate is an almost perfect fit.
- A 50-60 score means partial match with significant gaps.
- Below 40 means poor fit.
- ONLY evaluate based on the provided profile. Do NOT assume skills not listed.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON."""

USER_PROMPT_TEMPLATE = """## Candidate Profile
{profile_yaml}

## Job Description
Title: {job_title}
Company: {company}
Location: {location}

{job_description}

## Task
Score this candidate against this job. Return JSON in exactly this format:
{{
  "score": <integer 0-100>,
  "reasons": ["reason this is a good match", "another reason"],
  "gaps": ["skill or requirement the candidate lacks"]
}}"""

class ScoringEngine:
    def __init__(self, db_session: Session, llm_client: LLMClient, config: dict, profile: dict):
        self.db = db_session
        self.llm = llm_client
        self.min_score = config.get("application", {}).get("min_match_score", 60)
        self.profile = profile
        self.profile_yaml = yaml.dump(profile, sort_keys=False)

    def run(self, run_id: str) -> dict:
        stats = {"scored": 0, "skipped": 0, "errors": 0, "above_threshold": 0}
        
        jobs_to_score = self.db.query(Job).filter(
            Job.status == "DISCOVERED",
            Job.run_id == run_id
        ).all()
        
        for job in jobs_to_score:
            if not job.description or len(job.description.strip()) < 10:
                job.status = "SKIPPED"
                job.notes = "Skipped: Description too short or missing."
                self.db.commit()
                stats["skipped"] += 1
                continue
                
            system_prompt, user_prompt = self._build_prompt(job)
            
            try:
                response = self.llm.complete(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    response_format="json",
                    purpose="scoring",
                    job_id=job.id,
                    run_id=run_id
                )
                
                score = response.get("score", 0)
                reasons = response.get("reasons", [])
                gaps = response.get("gaps", [])
                
                # Clamp score
                if not isinstance(score, (int, float)):
                    score = 0
                score = max(0, min(100, int(score)))
                
                job.match_score = score
                job.match_reasons = json.dumps(reasons)
                job.match_gaps = json.dumps(gaps)
                job.scored_at = datetime.utcnow()
                
                if score >= self.min_score:
                    job.status = "SCORED"
                    stats["above_threshold"] += 1
                else:
                    job.status = "SKIPPED"
                    
                stats["scored"] += 1
                self.db.commit()
                
            except LLMResponseError as e:
                logging.error(f"Failed to score job {job.id}: {e}")
                job.notes = f"LLM Error: {e}"
                # Keep status DISCOVERED so it can be retried later
                self.db.commit()
                stats["errors"] += 1
            except Exception as e:
                logging.error(f"Unexpected error scoring job {job.id}: {e}")
                stats["errors"] += 1
                
        return stats

    def _build_prompt(self, job: Job) -> tuple[str, str]:
        user_prompt = USER_PROMPT_TEMPLATE.format(
            profile_yaml=self.profile_yaml,
            job_title=job.title,
            company=job.company,
            location=job.location or "Unknown",
            job_description=job.description
        )
        return SYSTEM_PROMPT, user_prompt
