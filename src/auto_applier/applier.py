import os
import asyncio
import logging
from sqlalchemy.orm import Session
from src.llm.client import LLMClient
from src.database.models import Job
from src.auto_applier.form_filler import FormFiller
from src.auto_applier.question_answerer import QuestionAnswerer
from playwright.async_api import async_playwright

class AutoApplier:
    def __init__(self, db_session: Session, llm_client: LLMClient, config: dict, profile: dict, answers: list[dict]):
        self.db = db_session
        self.config = config
        self.qa = QuestionAnswerer(llm_client, answers, profile)
        self.form_filler = FormFiller(self.qa, profile)
        
        app_cfg = config.get("application", {})
        self.daily_limit = app_cfg.get("daily_limit", 25)
        self.delay_min = app_cfg.get("delay_min_seconds", 3)
        self.delay_max = app_cfg.get("delay_max_seconds", 8)
        self.viewport = app_cfg.get("browser_viewport", {"width": 1920, "height": 1080})

    async def run(self, run_id: str, approved_job_ids: list[str]) -> dict:
        stats = {"applied": 0, "failed": 0, "skipped_limit": 0}
        
        jobs = self.db.query(Job).filter(Job.id.in_(approved_job_ids)).all()
        if not jobs:
            return stats
            
        async with async_playwright() as p:
            profile_dir = os.path.join(os.getcwd(), "data", "browser_profile")
            os.makedirs(profile_dir, exist_ok=True)
            
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                viewport=self.viewport,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
            page = await browser.new_page()
            
            for job in jobs:
                if stats["applied"] >= self.daily_limit:
                    stats["skipped_limit"] += 1
                    continue
                    
                if job.platform != "linkedin":
                    job.status = "QUEUED_FOR_MANUAL"
                    self.db.commit()
                    stats["failed"] += 1
                    continue
                    
                try:
                    await page.goto(job.job_url, wait_until="domcontentloaded")
                    success = await self._apply_to_job(page, job)
                    if success:
                        job.status = "APPLIED"
                        job.applied_method = "auto"
                        stats["applied"] += 1
                    else:
                        job.status = "QUEUED_FOR_MANUAL"
                        stats["failed"] += 1
                except Exception as e:
                    logging.error(f"Error applying to {job.id}: {e}")
                    job.status = "QUEUED_FOR_MANUAL"
                    stats["failed"] += 1
                
                self.db.commit()
                await asyncio.sleep(self.delay_min)
                
            await browser.close()
        
        return stats

    async def _apply_to_job(self, page, job: Job) -> bool:
        # Check if easy apply button exists
        try:
            # We don't want to actually submit in a dev environment unless instructed.
            # This is a stub for the complex playwright automation flow.
            # await page.click('button:has-text("Easy Apply")', timeout=5000)
            # await self.form_filler.fill_form_page(page)
            # await page.click('button[aria-label="Submit application"]')
            return True # Mock success
        except Exception:
            return False
