# Module 01: Discovery Engine

> **Depends on:** `00_shared_contracts.md` (DB schema, config schemas)
> **Files to create:** `src/discovery/__init__.py`, `src/discovery/engine.py`
> **External dependency:** `python-jobspy`
> **LLM required:** No
> **Estimated effort:** Small

---

## Purpose

Scrape job listings from multiple platforms (LinkedIn, Indeed, Glassdoor, Naukri, Google Jobs) using the JobSpy library, deduplicate them, and store them in the `jobs` table with status `DISCOVERED`.

---

## Input

- `config/search_filters.yaml` — list of search queries with title, location, experience level, work mode
- `config/profile.yaml` — only `preferences.companies_blacklist` (to exclude known bad companies)

## Output

- New rows in `jobs` table with `status = "DISCOVERED"`
- Updated `runs` table with `jobs_discovered` count

---

## File: `src/discovery/engine.py`

### Class: `DiscoveryEngine`

```python
class DiscoveryEngine:
    def __init__(self, db_session, config: dict, search_filters: dict, profile: dict):
        self.db = db_session
        self.config = config
        self.filters = search_filters
        self.blacklist = [c.lower() for c in profile.get("preferences", {}).get("companies_blacklist", [])]
    
    def run(self, run_id: str) -> int:
        """
        Execute all search queries across enabled platforms.
        Returns: number of new unique jobs discovered.
        
        Steps:
        1. For each search in search_filters.yaml:
           a. Call jobspy.scrape_jobs() with the search parameters
           b. Filter out blacklisted companies
           c. Filter out jobs matching exclude_keywords
           d. Compute dedup_hash for each job
           e. INSERT into jobs table (skip if dedup_hash already exists)
        2. Update runs table with jobs_discovered count
        """
        ...

    def _compute_dedup_hash(self, company: str, title: str, location: str) -> str:
        """SHA256 of normalized (lowercase, stripped) company+title+location"""
        ...

    def _is_blacklisted(self, company: str) -> bool:
        """Check if company is in blacklist"""
        ...

    def _matches_exclude_keywords(self, title: str, description: str) -> bool:
        """Check if job title or description contains any exclude_keywords"""
        ...
```

### JobSpy Usage

```python
from jobspy import scrape_jobs

# Example call for one search filter:
jobs_df = scrape_jobs(
    site_name=["linkedin", "indeed", "glassdoor"],  # enabled platforms from config
    search_term="Senior Software Engineer",
    location="Bangalore",
    results_wanted=50,
    hours_old=168,                    # 1 week = 168 hours
    country_indeed="India",
    linkedin_fetch_description=True,  # Get full JD
)

# jobs_df columns we use:
# - title, company, location, job_url, description, site, 
#   min_amount, max_amount, interval (salary), is_remote
```

### Mapping JobSpy columns → DB columns

| JobSpy Column | DB Column | Transform |
|---|---|---|
| `title` | `title` | Strip whitespace |
| `company` | `company` | Strip whitespace |
| `location` | `location` | Strip whitespace |
| `job_url` | `job_url` | As-is |
| `description` | `description` | Strip HTML tags, clean whitespace |
| `site` | `platform` | Map: `"linkedin"` → `"linkedin"`, etc. |
| `min_amount` / `max_amount` / `interval` | `salary_info` | Format: `"$50K-$80K/year"` or null |
| `is_remote` | `work_mode` | `True` → `"remote"`, else `"unknown"` |

---

## Error Handling

- If JobSpy fails for one platform → log error, continue with other platforms
- If JobSpy returns empty DataFrame → log warning, continue
- If a job has no `title` or `company` → skip that row
- If INSERT fails (duplicate dedup_hash) → skip silently (expected behavior)

---

## Test Scenarios (`tests/test_discovery.py`)

1. **Test dedup_hash generation:** Same company+title+location → same hash, regardless of casing/whitespace
2. **Test blacklist filtering:** Jobs from blacklisted companies are excluded
3. **Test keyword exclusion:** Jobs with "intern" in title are excluded
4. **Test DB insert:** New jobs get status `DISCOVERED` and correct timestamps
5. **Test duplicate skip:** Running discovery twice with same results → no duplicate rows
6. **Mock test:** Mock `jobspy.scrape_jobs()` to return a fixed DataFrame, verify correct DB inserts
