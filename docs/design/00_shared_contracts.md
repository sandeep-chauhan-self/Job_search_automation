# Module 00: Shared Contracts

> **Purpose:** This is the single source of truth for all inter-module communication.
> Every module reads/writes to the same SQLite database and reads from the same YAML config files.
> If you're implementing ANY module, read this document first.

---

## 1. Project Structure

```
c:\Users\scst1\2026\Job_search_automation\
│
├── config/
│   ├── config.yaml                  # System settings (LLM, limits, delays)
│   ├── secrets.yaml                 # API keys & credentials (gitignored)
│   ├── profile.yaml                 # User's master resume/profile data
│   ├── search_filters.yaml          # Job search parameters
│   └── answers.yaml                 # Pre-saved Q&A pairs for form filling
│
├── templates/
│   ├── resume_template.html         # HTML/CSS resume template
│   ├── resume_styles.css            # Stylesheet for resume
│   └── cover_letter_template.html   # HTML/CSS cover letter template
│
├── output/                          # Generated files (gitignored)
│   ├── resumes/                     # {job_id}_{company}_resume.pdf
│   ├── cover_letters/               # {job_id}_{company}_cover.pdf
│   ├── screenshots/                 # Auto-apply screenshots
│   └── logs/                        # New Q&A log, error logs
│       └── new_questions.log        # LLM-answered questions for manual review
│
├── src/
│   ├── main.py                      # CLI entry point
│   ├── orchestrator.py              # Pipeline coordinator
│   ├── discovery/
│   │   ├── __init__.py
│   │   └── engine.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── engine.py
│   ├── resume_factory/
│   │   ├── __init__.py
│   │   ├── tailoring.py             # LLM-based content tailoring
│   │   └── renderer.py              # HTML → PDF rendering
│   ├── auto_applier/
│   │   ├── __init__.py
│   │   ├── applier.py               # LinkedIn Easy Apply automation
│   │   ├── form_filler.py           # Form field handling
│   │   └── question_answerer.py     # Two-tier Q&A (lookup + LLM)
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI app
│   │   ├── routes.py                # API endpoints
│   │   └── static/                  # Frontend HTML/CSS/JS
│   │       ├── index.html
│   │       ├── styles.css
│   │       └── app.js
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py                # LiteLLM wrapper with retry + JSON validation
│   │   └── cost_tracker.py          # Token & cost logging
│   └── database/
│       ├── __init__.py
│       ├── models.py                # SQLAlchemy models
│       └── connection.py            # DB connection setup
│
├── data/                            # (gitignored)
│   └── jobs.db                      # SQLite database
│
├── tests/
│   ├── test_discovery.py
│   ├── test_scoring.py
│   ├── test_resume_factory.py
│   ├── test_auto_applier.py
│   ├── test_llm_client.py
│   └── test_dashboard.py
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 2. Database Schema (SQLite via SQLAlchemy)

**File:** `src/database/models.py`

### Table: `jobs`

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `TEXT` (UUID) | NO | `uuid4()` | Primary key |
| `title` | `TEXT` | NO | | Job title |
| `company` | `TEXT` | NO | | Company name |
| `location` | `TEXT` | YES | | Job location |
| `platform` | `TEXT` | NO | | One of: `linkedin`, `indeed`, `glassdoor`, `naukri`, `google_jobs` |
| `job_url` | `TEXT` | NO | | Direct URL to job posting |
| `description` | `TEXT` | YES | | Full job description (cleaned plain text) |
| `dedup_hash` | `TEXT` | NO | | UNIQUE. SHA256 of `lower(company+title+location)` |
| `status` | `TEXT` | NO | `DISCOVERED` | See status enum below |
| `match_score` | `INTEGER` | YES | | 0-100 match score from LLM |
| `match_reasons` | `TEXT` | YES | | JSON string: `["reason1", "reason2"]` |
| `match_gaps` | `TEXT` | YES | | JSON string: `["gap1", "gap2"]` |
| `resume_path` | `TEXT` | YES | | Path to generated resume PDF |
| `cover_letter_path` | `TEXT` | YES | | Path to generated cover letter PDF (null if skipped) |
| `salary_info` | `TEXT` | YES | | Raw salary string from listing |
| `work_mode` | `TEXT` | YES | | One of: `remote`, `hybrid`, `onsite`, `unknown` |
| `discovered_at` | `TEXT` | NO | `now()` | ISO 8601 timestamp |
| `scored_at` | `TEXT` | YES | | |
| `resume_generated_at` | `TEXT` | YES | | |
| `applied_at` | `TEXT` | YES | | |
| `applied_method` | `TEXT` | YES | | One of: `auto`, `manual` |
| `run_id` | `TEXT` | YES | | FK to `runs.id` — which run discovered this job |
| `notes` | `TEXT` | YES | | User-editable notes |

### Status Enum (string values)

```
DISCOVERED → SCORED → RESUME_READY → REVIEW_QUEUED → APPLIED
                                   → QUEUED_FOR_MANUAL → APPLIED
           → SKIPPED
APPLIED → INTERVIEW → OFFER
                    → REJECTED
        → REJECTED
        → GHOSTED
```

Valid values: `DISCOVERED`, `SCORED`, `SKIPPED`, `RESUME_READY`, `REVIEW_QUEUED`, `QUEUED_FOR_MANUAL`, `APPLIED`, `INTERVIEW`, `OFFER`, `REJECTED`, `GHOSTED`

### Table: `runs`

| Column | Type | Description |
|---|---|---|
| `id` | `TEXT` (UUID) | Primary key |
| `started_at` | `TEXT` | ISO 8601 |
| `completed_at` | `TEXT` | ISO 8601 (null if running) |
| `status` | `TEXT` | `RUNNING`, `COMPLETED`, `FAILED` |
| `jobs_discovered` | `INTEGER` | |
| `jobs_scored` | `INTEGER` | |
| `jobs_above_threshold` | `INTEGER` | |
| `resumes_generated` | `INTEGER` | |
| `auto_applied` | `INTEGER` | |
| `queued_for_manual` | `INTEGER` | |
| `errors` | `INTEGER` | |
| `total_llm_cost` | `REAL` | Sum of LLM costs in USD |
| `error_log` | `TEXT` | JSON string of error details |

### Table: `llm_usage`

| Column | Type | Description |
|---|---|---|
| `id` | `INTEGER` | Auto-increment PK |
| `run_id` | `TEXT` | FK to `runs.id` |
| `job_id` | `TEXT` | FK to `jobs.id` (nullable) |
| `purpose` | `TEXT` | `scoring`, `resume_tailoring`, `cover_letter`, `question_answering` |
| `model` | `TEXT` | e.g. `gpt-4o-mini` |
| `input_tokens` | `INTEGER` | |
| `output_tokens` | `INTEGER` | |
| `cost_usd` | `REAL` | |
| `timestamp` | `TEXT` | ISO 8601 |

---

## 3. Config File Schemas

### `config/config.yaml`

```yaml
# System configuration
llm:
  provider: "gpt-4o-mini"            # LiteLLM model string
  temperature: 0.3
  max_tokens: 2000
  fallback_provider: "ollama/llama3.1"  # Used if primary fails

application:
  daily_limit: 25                     # Max auto-applies per day
  min_match_score: 60                 # Jobs below this are SKIPPED
  delay_min_seconds: 3                # Min delay between actions
  delay_max_seconds: 8                # Max delay between actions
  generate_cover_letter: true         # Master toggle (also checks JD keywords)
  browser_viewport:
    width: 1920
    height: 1080

platforms:
  linkedin: true
  indeed: true
  glassdoor: true
  naukri: true
  google_jobs: true

ghosting:
  days_until_ghosted: 14              # Auto-mark as ghosted after N days
```

### `config/secrets.yaml` (GITIGNORED)

```yaml
llm_api_key: "sk-..."                # OpenAI / DeepSeek API key
linkedin:
  email: "user@example.com"
  password: "..."                     # Only used for initial browser login
```

### `config/profile.yaml`

```yaml
personal:
  name: "John Doe"
  email: "john@example.com"
  phone: "+91-9876543210"
  location: "Bangalore, India"
  linkedin_url: "https://linkedin.com/in/johndoe"
  github_url: "https://github.com/johndoe"
  portfolio_url: "https://johndoe.dev"

summary: |
  Senior Software Engineer with 6+ years of experience in full-stack development,
  specializing in Python, React, and cloud infrastructure. Led teams of 5-8 engineers
  at two startups. Passionate about building developer tools and automation.

experience:
  - title: "Senior Software Engineer"
    company: "TechCorp"
    location: "Bangalore, India"
    start_date: "2022-01"
    end_date: "present"
    bullets:
      - "Led migration of monolithic API to microservices, reducing latency by 40%"
      - "Built CI/CD pipeline serving 200+ deployments/week using GitHub Actions"
      - "Mentored 3 junior developers through code reviews and pair programming"

  - title: "Software Engineer"
    company: "StartupXYZ"
    location: "Mumbai, India"
    start_date: "2019-06"
    end_date: "2021-12"
    bullets:
      - "Developed real-time notification system handling 1M+ events/day"
      - "Implemented OAuth2 SSO reducing login friction by 60%"

skills:
  languages: ["Python", "JavaScript", "TypeScript", "Go"]
  frameworks: ["React", "FastAPI", "Django", "Next.js"]
  tools: ["Docker", "Kubernetes", "AWS", "PostgreSQL", "Redis"]
  certifications: ["AWS Solutions Architect Associate"]

education:
  - degree: "B.Tech Computer Science"
    institution: "IIT Delhi"
    year: 2019

preferences:
  target_roles: ["Senior Software Engineer", "Staff Engineer", "Tech Lead"]
  target_locations: ["Bangalore", "Remote"]
  work_mode: ["remote", "hybrid"]
  min_salary: "25 LPA"
  industries_preferred: ["SaaS", "Developer Tools", "Fintech"]
  companies_blacklist: ["SpamCorp", "SketchyInc"]
```

### `config/search_filters.yaml`

```yaml
searches:
  - title: "Senior Software Engineer"
    location: "Bangalore"
    experience_level: "mid_senior"
    work_mode: "remote"
    date_posted: "week"                # past24h, week, month
    
  - title: "Staff Engineer"
    location: "India"
    experience_level: "senior"
    work_mode: "remote"
    date_posted: "week"

  - title: "Tech Lead"
    location: "Bangalore"
    experience_level: "mid_senior"
    work_mode: "hybrid"
    date_posted: "week"

exclude_keywords: ["intern", "junior", "fresher", "unpaid"]
include_keywords: ["python", "react"]
```

### `config/answers.yaml`

```yaml
# Pre-saved answers for common application questions
# Format: question_pattern (case-insensitive substring match) → answer

- pattern: "years of experience"
  answer: "6"
  type: "number"

- pattern: "authorized to work"
  answer: "Yes"
  type: "radio"

- pattern: "visa sponsorship"
  answer: "No"
  type: "radio"

- pattern: "salary"
  answer: "2500000"
  type: "number"

- pattern: "notice period"
  answer: "30 days"
  type: "text"

- pattern: "willing to relocate"
  answer: "Yes"
  type: "radio"

- pattern: "gender"
  answer: "Male"
  type: "dropdown"

- pattern: "start date"
  answer: "Within 30 days"
  type: "text"
```

---

## 4. Shared Python Interfaces

### LLM Client Interface

Every module that calls LLM uses this interface. Implemented in `src/llm/client.py`.

```python
# Interface contract — actual implementation in Module 07 (LLM Layer)

class LLMClient:
    def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: str = "json",  # "json" or "text"
        max_retries: int = 2
    ) -> dict | str:
        """
        Send a prompt to the configured LLM provider.
        
        If response_format="json":
          - Parses response as JSON
          - On parse failure: retries up to max_retries
          - On total failure: raises LLMResponseError
          - Returns: dict
          
        If response_format="text":
          - Returns raw string
          
        Logs token usage to llm_usage table automatically.
        """
        ...

    def get_run_cost(self, run_id: str) -> float:
        """Return total USD cost for a run."""
        ...
```

### Database Session Interface

```python
# Interface contract — implemented in src/database/connection.py

from sqlalchemy.orm import Session

def get_db() -> Session:
    """Returns a SQLAlchemy session connected to data/jobs.db"""
    ...
```

### Config Loader Interface

```python
# Interface contract — implemented in src/config_loader.py

import yaml

def load_config() -> dict:
    """Load and merge all YAML config files. Returns nested dict."""
    ...

def load_profile() -> dict:
    """Load config/profile.yaml"""
    ...

def load_search_filters() -> dict:
    """Load config/search_filters.yaml"""
    ...

def load_answers() -> list[dict]:
    """Load config/answers.yaml"""
    ...
```

---

## 5. Dependencies (requirements.txt)

```
# Core
python-jobspy>=2.0          # Job scraping
litellm>=1.40               # LLM routing
playwright>=1.40            # Browser automation + PDF generation
sqlalchemy>=2.0             # Database ORM
fastapi>=0.110              # Dashboard backend
uvicorn>=0.29               # ASGI server
pyyaml>=6.0                 # Config parsing
jinja2>=3.1                 # HTML template rendering

# Utilities
python-dateutil>=2.9
httpx>=0.27                 # Async HTTP (for FastAPI)

# Testing
pytest>=8.0
pytest-asyncio>=0.23
```

---

## 6. .gitignore

```
config/secrets.yaml
data/
output/
__pycache__/
*.pyc
.env
```

---

## 7. Module Dependency Order (Build Sequence)

```
Phase 0: 00_shared_contracts (this doc — DB + config + interfaces)
         ↓
Phase 1: 07_llm_layer + database/models.py + config_loader.py
         ↓ (these have zero dependencies on other modules)
Phase 2: 01_discovery_engine (depends on: DB, config)
         02_scoring_engine (depends on: DB, config, LLM client)
         ↓ (can be built in parallel)
Phase 3: 03_resume_factory (depends on: DB, config, LLM client, Jinja2)
         ↓
Phase 4: 04_auto_applier (depends on: DB, config, LLM client, Playwright)
         05_semi_auto_queue (depends on: DB only — very simple)
         ↓ (can be built in parallel)
Phase 5: 06_dashboard (depends on: DB, all modules for triggering runs)
         ↓
Phase 6: 08_orchestrator (depends on: all modules — wires them together)
```
