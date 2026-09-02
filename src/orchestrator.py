import uuid
import logging
from datetime import datetime
from src.database.connection import get_db
from src.database.models import Run
from src.config_loader import load_config, load_secrets, load_profile, load_search_filters, load_answers
from src.llm.client import LLMClient
from src.discovery.engine import DiscoveryEngine
from src.scoring.engine import ScoringEngine
from src.resume_factory.tailoring import ResumeTailor
from src.resume_factory.renderer import ResumeRenderer
from src.auto_applier.applier import AutoApplier

class Orchestrator:
    def __init__(self):
        # Load configs
        self.config = load_config()
        self.secrets = load_secrets()
        self.profile = load_profile()
        self.search_filters = load_search_filters()
        
        answers_data = load_answers()
        self.answers = answers_data if isinstance(answers_data, list) else answers_data.get("answers", [])
        
        # Setup DB
        self.db = get_db()
        
        # Setup Core Services
        self.llm = LLMClient(self.db, self.config, self.secrets)
        
        # Setup Engines
        self.discovery = DiscoveryEngine(self.db, self.config, self.search_filters, self.profile)
        self.scoring = ScoringEngine(self.db, self.llm, self.config, self.profile)
        self.tailor = ResumeTailor(self.llm, self.profile)
        self.renderer = ResumeRenderer()
        self.applier = AutoApplier(self.db, self.llm, self.config, self.profile, self.answers)

    def run_pipeline(self):
        run_id = str(uuid.uuid4())
        logging.info(f"Starting pipeline run: {run_id}")
        
        # Create Run record
        run_record = Run(id=run_id, status="RUNNING")
        self.db.add(run_record)
        self.db.commit()
        
        try:
            # Phase 1: Discovery
            logging.info("Running Discovery Engine...")
            jobs_found = self.discovery.run(run_id)
            logging.info(f"Discovered {jobs_found} new jobs.")
            run_record.jobs_discovered = jobs_found
            
            # Phase 2: Scoring
            logging.info("Running Scoring Engine...")
            scoring_stats = self.scoring.run(run_id)
            logging.info(f"Scoring complete. Passed threshold: {scoring_stats['above_threshold']}")
            run_record.jobs_scored = scoring_stats["scored"]
            
            # We stop here for human-in-the-loop review.
            
            run_record.status = "COMPLETED"
            run_record.completed_at = datetime.utcnow()
            self.db.commit()
            logging.info("Pipeline completed successfully.")
            
        except Exception as e:
            logging.error(f"Pipeline failed: {e}")
            run_record.status = "FAILED"
            run_record.completed_at = datetime.utcnow()
            self.db.commit()
            
    async def run_apply(self, job_ids: list[str]):
        """Runs the tailoring and apply process for specific jobs (human-in-the-loop entrypoint)"""
        run_id = str(uuid.uuid4())
        logging.info(f"Starting apply run: {run_id} for {len(job_ids)} jobs")
        
        logging.info("Running Auto-Applier...")
        stats = await self.applier.run(run_id, job_ids)
        logging.info(f"Apply complete. Stats: {stats}")
        return stats
