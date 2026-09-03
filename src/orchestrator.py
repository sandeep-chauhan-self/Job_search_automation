import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from src.auto_applier.applier import AutoApplier
from src.config_loader import (
    load_answers,
    load_config,
    load_profile,
    load_search_filters,
    load_secrets,
)
from src.database.connection import get_db
from src.database.models import Job, Run
from src.discovery.engine import DiscoveryEngine
from src.llm.client import LLMClient
from src.resume_factory.renderer import ResumeRenderer
from src.resume_factory.tailoring import ResumeTailor
from src.scoring.engine import ScoringEngine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _NullReporter:
    """No-op progress sink so CLI runs work without the dashboard."""

    def log(self, message: str, level: str = "info") -> None:
        logging.log(logging.ERROR if level == "error" else logging.INFO, message)

    def set_phase(self, phase: str, current: int = 0, total: int = 0) -> None:
        pass

    def set_progress(self, current: int, total: int) -> None:
        pass

    def merge_stats(self, stats: dict) -> None:
        pass

    def bind_run_id(self, run_id: str) -> None:
        pass

    def cancel_requested(self) -> bool:
        return False


class Orchestrator:
    def __init__(self, reporter=None):
        self.reporter = reporter or _NullReporter()

        self.config = load_config()
        self.secrets = load_secrets()
        self.profile = load_profile()
        self.search_filters = load_search_filters()

        answers_data = load_answers()
        self.answers = answers_data if isinstance(answers_data, list) else answers_data.get("answers", [])

        self.db = get_db()

        self.llm = LLMClient(self.db, self.config, self.secrets)

        self.discovery = DiscoveryEngine(self.db, self.config, self.search_filters, self.profile, self.reporter)
        self.scoring = ScoringEngine(self.db, self.llm, self.config, self.profile, self.reporter)
        self.tailor = ResumeTailor(self.llm, self.profile)
        self.renderer = ResumeRenderer()
        self.applier = AutoApplier(self.db, self.llm, self.config, self.profile, self.answers, self.reporter)

    # -- discovery + scoring -------------------------------------------------

    def run_pipeline(self) -> str:
        run_id = str(uuid.uuid4())
        self.reporter.bind_run_id(run_id)

        run_record = Run(id=run_id, status="RUNNING")
        self.db.add(run_record)
        self.db.commit()

        try:
            self.reporter.set_phase("discovery")
            self.reporter.log("Discovery: scraping configured job boards...")
            jobs_found = self.discovery.run(run_id)
            run_record.jobs_discovered = jobs_found
            self.db.commit()
            self.reporter.log(f"Discovery: {jobs_found} new jobs stored.")
            self.reporter.merge_stats({"jobs_discovered": jobs_found})

            if self.reporter.cancel_requested():
                return self._close_run(run_record, "CANCELLED")

            self.reporter.set_phase("scoring")
            self.reporter.log("Scoring: sending jobs to the LLM for match analysis...")
            scoring_stats = self.scoring.run(run_id)
            run_record.jobs_scored = scoring_stats["scored"]
            run_record.jobs_above_threshold = scoring_stats["above_threshold"]
            self.db.commit()
            self.reporter.log(
                f"Scoring: {scoring_stats['scored']} scored, "
                f"{scoring_stats['above_threshold']} above threshold, "
                f"{scoring_stats['errors']} errors."
            )
            self.reporter.merge_stats(scoring_stats)

            self.reporter.log("Pipeline paused for review. Approve jobs in the dashboard to continue.")
            return self._close_run(run_record, "COMPLETED")

        except Exception as exc:
            run_record.error_log = str(exc)
            self._close_run(run_record, "FAILED")
            raise

    # -- resume generation ---------------------------------------------------

    async def run_prepare(self, job_ids: list[str], run_id: str | None = None) -> dict:
        """Tailor + render resume/cover letter PDFs so jobs reach RESUME_READY."""
        run_id = run_id or str(uuid.uuid4())
        self.reporter.bind_run_id(run_id)
        stats = {"prepared": 0, "failed": 0}

        jobs = self.db.query(Job).filter(Job.id.in_(job_ids)).all()
        total = len(jobs)
        self.reporter.set_phase("tailoring", 0, total)
        self.reporter.log(f"Resume factory: preparing documents for {total} job(s).")

        generate_cover = self.config.get("application", {}).get("generate_cover_letter", True)

        for index, job in enumerate(jobs, start=1):
            if self.reporter.cancel_requested():
                self.reporter.log("Resume factory: cancelled before finishing.", "warn")
                break

            self.reporter.set_progress(index, total)
            try:
                job_dict = {
                    "title": job.title,
                    "company": job.company,
                    "description": job.description or "",
                    "match_reasons": job.match_reasons or "[]",
                    "match_gaps": job.match_gaps or "[]",
                }

                self.reporter.log(f"Tailoring resume for {job.title} at {job.company}...")
                tailored = self.tailor.tailor_for_job(job_dict, job.id, run_id)
                job.resume_path = await self.renderer.render_resume_pdf(tailored, job.id, job.company)

                if generate_cover and self.tailor.should_generate_cover_letter(job.description or ""):
                    self.reporter.log(f"Writing cover letter for {job.company}...")
                    letter = self.tailor.generate_cover_letter(job_dict, job.id, run_id)
                    job.cover_letter_path = await self.renderer.render_cover_letter_pdf(
                        letter, self.profile.get("personal", {}), job.title, job.company, job.id
                    )

                job.status = "RESUME_READY"
                job.resume_generated_at = _utcnow()
                self.db.commit()
                stats["prepared"] += 1
                self.reporter.log(f"Documents ready for {job.company}.")

            except Exception as exc:
                self.db.rollback()
                job.notes = f"Resume generation failed: {exc}"
                self.db.commit()
                stats["failed"] += 1
                self.reporter.log(f"Resume generation failed for {job.company}: {exc}", "error")

        self.reporter.merge_stats(stats)
        return stats

    # -- applying ------------------------------------------------------------

    async def run_apply(self, job_ids: list[str], prepare_first: bool = True) -> dict:
        run_id = str(uuid.uuid4())
        self.reporter.bind_run_id(run_id)

        stats: dict = {}
        if prepare_first:
            pending = [
                job.id
                for job in self.db.query(Job).filter(Job.id.in_(job_ids)).all()
                if job.status != "RESUME_READY" or not job.resume_path
            ]
            if pending:
                stats.update(await self.run_prepare(pending, run_id))

        if self.reporter.cancel_requested():
            return stats

        self.reporter.set_phase("applying")
        apply_stats = await self.applier.run(run_id, job_ids)
        stats.update(apply_stats)
        self.reporter.merge_stats(apply_stats)
        self.reporter.log(f"Apply finished: {json.dumps(apply_stats)}")
        return stats

    # -- helpers -------------------------------------------------------------

    def _close_run(self, run_record: Run, status: str) -> str:
        run_record.status = status
        run_record.completed_at = _utcnow()
        self.db.commit()
        return run_record.id

    def close(self) -> None:
        self.db.close()


def run_discovery_job(reporter) -> None:
    """Entry point used by the dashboard's background run manager."""
    orchestrator = Orchestrator(reporter)
    try:
        orchestrator.run_pipeline()
    finally:
        orchestrator.close()


def run_apply_job(reporter, job_ids: list[str]) -> None:
    orchestrator = Orchestrator(reporter)
    try:
        asyncio.run(orchestrator.run_apply(job_ids))
    finally:
        orchestrator.close()


def run_prepare_job(reporter, job_ids: list[str]) -> None:
    orchestrator = Orchestrator(reporter)
    try:
        asyncio.run(orchestrator.run_prepare(job_ids))
    finally:
        orchestrator.close()
