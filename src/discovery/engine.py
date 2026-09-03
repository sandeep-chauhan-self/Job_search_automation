import hashlib
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from src.database.models import Job, Run

# Optional at import time: a missing/broken jobspy install must not stop the
# dashboard or the rest of the pipeline from loading. Only run() requires it.
try:
    from jobspy import scrape_jobs
except ImportError:  # pragma: no cover - depends on local environment
    scrape_jobs = None

# config.yaml uses friendly platform keys; jobspy's Site enum uses its own names.
PLATFORM_SITE_MAP = {
    "google_jobs": "google",
    "zip_recruiter": "zip_recruiter",
}

class DiscoveryEngine:
    def __init__(self, db_session: Session, config: dict, search_filters: dict, profile: dict, reporter=None):
        self.db = db_session
        self.config = config
        self.filters = search_filters
        self.profile = profile
        self.reporter = reporter
        self.blacklist = [c.lower() for c in profile.get("preferences", {}).get("companies_blacklist", [])]

    def _log(self, message: str, level: str = "info") -> None:
        if self.reporter:
            self.reporter.log(message, level)
        else:
            logging.log(logging.ERROR if level == "error" else logging.INFO, message)

    def run(self, run_id: str) -> int:
        if scrape_jobs is None:
            raise RuntimeError("python-jobspy is not installed. Run: pip install python-jobspy")

        jobs_discovered = 0
        searches = self.filters.get("searches", [])
        exclude_keywords = [k.lower() for k in self.filters.get("exclude_keywords", [])]
        
        # Determine enabled platforms
        platforms_config = self.config.get("platforms", {})
        enabled_platforms = [PLATFORM_SITE_MAP.get(k, k) for k, v in platforms_config.items() if v]
        if not enabled_platforms:
            return 0
            
        for search in searches:
            title = search.get("title", "")
            location = search.get("location", "")
            
            try:
                jobs_df = scrape_jobs(
                    site_name=enabled_platforms,
                    search_term=title,
                    location=location,
                    results_wanted=50,
                    hours_old=168,
                    country_indeed="India",
                    linkedin_fetch_description=True
                )
            except Exception as e:
                self._log(f"Discovery: error scraping '{title}' in '{location}': {e}", "error")
                continue
                
            if jobs_df is None or jobs_df.empty:
                self._log(f"Discovery: no results for '{title}' in '{location}'.")
                continue

            self._log(f"Discovery: {len(jobs_df)} raw result(s) for '{title}' in '{location}'.")

            for _, row in jobs_df.iterrows():
                job_title = str(row.get("title", "")).strip()
                company = str(row.get("company", "")).strip()
                job_location = str(row.get("location", "")).strip()
                
                if not job_title or not company or str(job_title) == "nan" or str(company) == "nan":
                    continue
                    
                if self._is_blacklisted(company):
                    continue
                    
                description = str(row.get("description", ""))
                if str(description) == "nan":
                    description = ""
                
                if self._matches_exclude_keywords(job_title, description, exclude_keywords):
                    continue
                    
                dedup_hash = self._compute_dedup_hash(company, job_title, job_location)
                
                # Check if exists
                exists = self.db.query(Job).filter(Job.dedup_hash == dedup_hash).first()
                if exists:
                    continue
                
                site = str(row.get("site", "")).lower()
                url = str(row.get("job_url", ""))
                
                min_amt = row.get("min_amount")
                max_amt = row.get("max_amount")
                interval = row.get("interval")
                salary_info = None
                if min_amt and str(min_amt) != "nan":
                    salary_info = f"{min_amt}-{max_amt}/{interval}"
                    
                is_remote = row.get("is_remote")
                work_mode = "remote" if is_remote is True or str(is_remote).lower() == "true" else "unknown"
                
                job = Job(
                    title=job_title,
                    company=company,
                    location=job_location,
                    platform=site,
                    job_url=url,
                    description=description,
                    dedup_hash=dedup_hash,
                    salary_info=salary_info,
                    work_mode=work_mode,
                    run_id=run_id
                )
                self.db.add(job)
                try:
                    self.db.commit()
                    jobs_discovered += 1
                except Exception as e:
                    self.db.rollback()
                    self._log(f"Discovery: failed to insert job {job_title} at {company}: {e}", "error")
                    
        return jobs_discovered

    def _compute_dedup_hash(self, company: str, title: str, location: str) -> str:
        s = f"{company.lower().strip()}|{title.lower().strip()}|{location.lower().strip()}"
        return hashlib.sha256(s.encode('utf-8')).hexdigest()

    def _is_blacklisted(self, company: str) -> bool:
        return company.lower().strip() in self.blacklist

    def _matches_exclude_keywords(self, title: str, description: str, exclude_keywords: List[str]) -> bool:
        t = title.lower()
        d = description.lower()
        for kw in exclude_keywords:
            if kw in t or kw in d:
                return True
        return False
