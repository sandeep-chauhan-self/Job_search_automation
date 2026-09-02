# Module 02: Scoring Engine

> **Depends on:** `00_shared_contracts.md`, `07_llm_layer.md`
> **Files to create:** `src/scoring/__init__.py`, `src/scoring/engine.py`
> **External dependency:** LLM client (from LLM layer)
> **LLM required:** Yes
> **Estimated effort:** Small

---

## Purpose

Take all jobs with `status = "DISCOVERED"`, send each job description + user profile to the LLM for match scoring, and update each job with a match score (0-100), match reasons, match gaps, and new status (`SCORED` or `SKIPPED`).

---

## Input

- DB: All jobs where `status = "DISCOVERED"`
- `config/profile.yaml` — user's full profile for comparison
- `config/config.yaml` — `llm.provider`, `application.min_match_score`

## Output

- Updated `jobs` rows: `status` → `SCORED` or `SKIPPED`, populated `match_score`, `match_reasons`, `match_gaps`, `scored_at`
- `llm_usage` rows logged per call

---

## File: `src/scoring/engine.py`

### Class: `ScoringEngine`

```python
class ScoringEngine:
    def __init__(self, db_session, llm_client: LLMClient, config: dict, profile: dict):
        self.db = db_session
        self.llm = llm_client
        self.min_score = config["application"]["min_match_score"]
        self.profile = profile

    def run(self, run_id: str) -> dict:
        """
        Score all DISCOVERED jobs.
        Returns: {"scored": N, "skipped": M, "errors": E}
        
        Steps:
        1. Query all jobs WHERE status = "DISCOVERED" AND run_id = current
        2. For each job:
           a. Build prompt (profile + JD)
           b. Call LLM with response_format="json"
           c. Parse response → extract score, reasons, gaps
           d. If score >= min_match_score → status = "SCORED"
           e. If score < min_match_score → status = "SKIPPED"
           f. Update DB row
        3. Update runs table with jobs_scored, jobs_above_threshold
        """
        ...

    def _build_prompt(self, job_description: str) -> tuple[str, str]:
        """
        Returns (system_prompt, user_prompt) for scoring.
        """
        ...
```

---

## LLM Prompt (Exact Text)

### System Prompt

```
You are a career match scoring engine. You analyze job descriptions against a candidate's profile and provide a match score.

Rules:
- Score from 0 to 100 based on how well the candidate's experience matches the job requirements.
- Be realistic. A 90+ score means the candidate is an almost perfect fit.
- A 50-60 score means partial match with significant gaps.
- Below 40 means poor fit.
- ONLY evaluate based on the provided profile. Do NOT assume skills not listed.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.
```

### User Prompt Template

```
## Candidate Profile
{profile_yaml_as_text}

## Job Description
Title: {job_title}
Company: {company}
Location: {location}

{job_description}

## Task
Score this candidate against this job. Return JSON in exactly this format:
{
  "score": <integer 0-100>,
  "reasons": ["reason this is a good match", "another reason"],
  "gaps": ["skill or requirement the candidate lacks"]
}
```

### Expected LLM Response (JSON)

```json
{
  "score": 78,
  "reasons": [
    "6 years Python experience matches requirement",
    "Microservices migration experience directly relevant",
    "AWS certification aligns with cloud infrastructure need"
  ],
  "gaps": [
    "No Kubernetes experience mentioned, job requires it",
    "Job asks for ML/AI experience, not in profile"
  ]
}
```

---

## Error Handling

- LLM returns invalid JSON → retry once (max_retries=2 in LLMClient), then mark job as `DISCOVERED` (leave for next run)
- LLM returns score outside 0-100 → clamp to valid range
- LLM times out → skip job, log error, continue with next
- Empty job description → skip job, set status `SKIPPED`

---

## Test Scenarios (`tests/test_scoring.py`)

1. **Test prompt building:** Verify profile and JD are correctly injected into prompt template
2. **Test score threshold:** Job with score 55 + min_score 60 → status `SKIPPED`
3. **Test score above threshold:** Job with score 75 + min_score 60 → status `SCORED`
4. **Test invalid JSON handling:** Mock LLM returning bad JSON → verify retry and graceful failure
5. **Test DB update:** After scoring, verify `match_score`, `match_reasons`, `match_gaps`, `scored_at` are set
6. **Mock test:** Mock LLMClient to return fixed scores, verify correct status transitions
