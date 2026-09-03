import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from src import constants as C
from src import corpus
from src.auto_applier.form_filler import FormFiller
from src.auto_applier.question_answerer import QuestionAnswerer
from src.database.models import Job
from src.llm.client import LLMClient
from src.settings import OUTPUT_DIR

SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshots")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AutoApplier:
    def __init__(
        self,
        db_session: Session,
        llm_client: LLMClient,
        config: dict,
        profile: dict,
        answers: list[dict],
        reporter=None,
    ):
        self.db = db_session
        self.config = config
        self.reporter = reporter
        self.qa = QuestionAnswerer(llm_client, answers, profile)
        self.form_filler = FormFiller(self.qa, profile)

        app_cfg = config.get("application", {})
        self.daily_limit = app_cfg.get("daily_limit", 25)
        self.delay_min = app_cfg.get("delay_min_seconds", 3)
        self.delay_max = app_cfg.get("delay_max_seconds", 8)
        self.viewport = app_cfg.get("browser_viewport", {"width": 1920, "height": 1080})
        # dry_run submits nothing; it walks the form and screenshots the final step.
        self.dry_run = app_cfg.get("dry_run", True)
        self.headless = app_cfg.get("headless", False)

    def _log(self, message: str, level: str = "info") -> None:
        if self.reporter:
            self.reporter.log(message, level)
        else:
            logging.log(logging.ERROR if level == "error" else logging.INFO, message)

    def _cancelled(self) -> bool:
        return bool(self.reporter and self.reporter.cancel_requested())

    def _applied_today(self) -> int:
        since = _utcnow() - timedelta(days=1)
        return self.db.query(Job).filter(Job.status == "APPLIED", Job.applied_at >= since).count()

    async def run(self, run_id: str, approved_job_ids: list[str]) -> dict:
        stats = {"applied": 0, "failed": 0, "skipped_limit": 0, "queued_manual": 0}

        jobs = self.db.query(Job).filter(Job.id.in_(approved_job_ids)).all()
        if not jobs:
            self._log("Apply: no matching jobs found.", "warn")
            return stats

        remaining = max(0, self.daily_limit - self._applied_today())
        if remaining == 0:
            self._log(f"Apply: daily limit of {self.daily_limit} already reached.", "warn")
            stats["skipped_limit"] = len(jobs)
            return stats

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        mode = "DRY RUN (nothing will be submitted)" if self.dry_run else "LIVE"
        self._log(f"Apply: launching browser in {mode} mode for {len(jobs)} job(s).")

        async with async_playwright() as p:
            profile_dir = os.path.join(os.getcwd(), "data", "browser_profile")
            os.makedirs(profile_dir, exist_ok=True)

            browser = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=self.headless,
                viewport=self.viewport,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()

            try:
                if not await self._ensure_logged_in(page):
                    stats["failed"] = len(jobs)
                    return stats

                for index, job in enumerate(jobs, start=1):
                    if self._cancelled():
                        self._log("Apply: cancelled by user.", "warn")
                        break

                    if self.reporter:
                        self.reporter.set_progress(index, len(jobs))

                    if stats["applied"] >= remaining:
                        stats["skipped_limit"] += 1
                        continue

                    if job.platform != "linkedin":
                        job.notes = "Auto-apply supports LinkedIn Easy Apply only."
                        corpus.change_status(
                            self.db, job, C.STATUS_QUEUED_FOR_MANUAL,
                            reason=f"{job.platform} is not supported by auto-apply", commit=False,
                        )
                        self.db.commit()
                        stats["queued_manual"] += 1
                        self._log(f"Queued for manual: {job.company} ({job.platform}).", "warn")
                        continue

                    if not job.resume_path or not os.path.exists(job.resume_path):
                        job.notes = "No tailored resume on disk - run Prepare first."
                        corpus.change_status(
                            self.db, job, C.STATUS_QUEUED_FOR_MANUAL,
                            reason="No tailored resume on disk", commit=False,
                        )
                        self.db.commit()
                        stats["queued_manual"] += 1
                        self._log(f"Queued for manual: {job.company} has no resume PDF.", "warn")
                        continue

                    self._log(f"Applying to {job.title} at {job.company}...")
                    self.qa.audit.clear()
                    try:
                        await page.goto(job.job_url, wait_until="domcontentloaded", timeout=45000)
                        submitted = await self._apply_to_job(page, job)

                        self._record_answers(job)

                        if submitted:
                            method = "dry_run" if self.dry_run else "auto"
                            corpus.change_status(
                                self.db, job, C.STATUS_APPLIED,
                                reason=f"Submitted via {method}", method=method, commit=False,
                            )
                            stats["applied"] += 1
                            self._log(f"{'Simulated' if self.dry_run else 'Submitted'} application to {job.company}.")
                        else:
                            corpus.change_status(
                                self.db, job, C.STATUS_QUEUED_FOR_MANUAL,
                                reason=job.notes or "Auto-apply could not complete", commit=False,
                            )
                            stats["failed"] += 1
                            self._log(f"Could not auto-apply to {job.company} - queued for manual.", "warn")
                    except Exception as exc:
                        job.notes = f"Auto-apply error: {exc}"
                        corpus.change_status(
                            self.db, job, C.STATUS_QUEUED_FOR_MANUAL, reason=str(exc), commit=False,
                        )
                        stats["failed"] += 1
                        self._log(f"Error applying to {job.company}: {exc}", "error")

                    self.db.commit()
                    await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))
            finally:
                await browser.close()

        return stats

    async def _apply_to_job(self, page, job: Job) -> bool:
        """Drive LinkedIn Easy Apply. Returns True when the application reached submission."""
        easy_apply = page.locator('button.jobs-apply-button, button:has-text("Easy Apply")').first
        try:
            await easy_apply.wait_for(state="visible", timeout=8000)
        except Exception:
            job.notes = "No Easy Apply button - external application required."
            return False

        await easy_apply.click()
        await page.wait_for_timeout(1500)

        for step in range(12):
            if self._cancelled():
                return False

            await self.form_filler.fill_form_page(page, job.resume_path)

            submit = page.locator('button[aria-label*="Submit application"]').first
            if await submit.count() > 0 and await submit.is_visible():
                shot = os.path.join(SCREENSHOT_DIR, f"{job.id}_final.png")
                await page.screenshot(path=shot)
                if self.dry_run:
                    self._log(f"Dry run: stopping before submit. Screenshot: {shot}", "warn")
                    await self._dismiss_modal(page)
                    return True
                await submit.click()
                await page.wait_for_timeout(2500)
                await page.screenshot(path=os.path.join(SCREENSHOT_DIR, f"{job.id}_submitted.png"))
                return True

            advance = page.locator(
                'button[aria-label*="Continue to next step"], button[aria-label*="Review your application"]'
            ).first
            if await advance.count() == 0 or not await advance.is_visible():
                job.notes = f"Stuck on Easy Apply step {step + 1} - unanswered required field."
                await page.screenshot(path=os.path.join(SCREENSHOT_DIR, f"{job.id}_stuck.png"))
                await self._dismiss_modal(page)
                return False

            await advance.click()
            await page.wait_for_timeout(1200)

        job.notes = "Easy Apply exceeded 12 steps - aborted."
        await self._dismiss_modal(page)
        return False

    async def _ensure_logged_in(self, page) -> bool:
        """Without a LinkedIn session every job silently fails to find Easy Apply.

        Checking once up front turns that into one clear message instead of N
        confusing per-job failures.
        """
        try:
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            self._log(f"Apply: could not reach LinkedIn ({exc}).", "error")
            return False

        if "/feed" in page.url and await page.locator("nav").count() > 0:
            return True

        if self.headless:
            self._log(
                "Apply: not signed in to LinkedIn. Set application.headless to false in "
                "config.yaml and run again - a browser will open for you to sign in once. "
                "The session is then reused from data/browser_profile.",
                "error",
            )
            return False

        self._log(
            "Apply: not signed in. Sign in to LinkedIn in the open browser window - "
            "waiting up to 3 minutes. This is only needed once.",
            "warn",
        )
        try:
            await page.wait_for_url("**/feed/**", timeout=180000)
            self._log("Apply: signed in. Session saved for next time.")
            return True
        except Exception:
            self._log("Apply: sign-in did not complete in time. Aborting.", "error")
            return False

    async def _dismiss_modal(self, page) -> None:
        try:
            await page.locator('button[aria-label="Dismiss"]').first.click(timeout=3000)
            await page.locator('button:has-text("Discard")').first.click(timeout=3000)
        except Exception:
            pass

    def _record_answers(self, job: Job) -> None:
        """Keep what was submitted on your behalf, so a wrong answer is traceable."""
        if not self.qa.audit:
            return
        lines = [f"[{a['source']}] {a['question']} -> {a['answer']}" for a in self.qa.audit]
        llm_count = sum(1 for a in self.qa.audit if a["source"] == "llm")
        corpus.record_event(
            self.db,
            job.id,
            C.EVENT_NOTE,
            f"Form answers submitted ({len(lines)} fields, {llm_count} generated)",
            detail="\n".join(lines),
            commit=False,
        )
