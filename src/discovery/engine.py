import hashlib
import logging
from typing import List, Dict, Any
from jobspy import scrape_jobs
from sqlalchemy.orm import Session
from src.database.models import Job, Run

class DiscoveryEngine:
    def __init__(self, db_session: Session, config: dict, search_filters: dict, profile: dict):
        self.db = db_session
        self.config = config
        self.filters = search_filters
        self.profile = profile
        self.blacklist = [c.lower() for c in profile.get("preferences", {}).get("companies_blacklist", [])]
        
    def run(self, run_id: str) -> int:
        jobs_discovered = 0
        searches = self.filters.get("searches", [])
        exclude_keywords = [k.lower() for k in self.filters.get("exclude_keywords", [])]
        
        # Determine enabled platforms mapped to JobSpy supported sites
        platforms_config = self.config.get("platforms", {})
        site_map = {
            "linkedin": "linkedin",
            "indeed": "indeed",
            "glassdoor": "glassdoor",
            "zip_recruiter": "zip_recruiter",
            "google_jobs": "google",
            "google": "google"
        }
        enabled_platforms = [site_map[k] for k, v in platforms_config.items() if v and k in site_map]
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
                logging.error(f"Error scraping for {title} in {location}: {e}")
                continue
                
            if jobs_df is None or jobs_df.empty:
                continue
                
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
                    logging.warning(f"Failed to insert job {job_title} at {company}: {e}")
                    
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
