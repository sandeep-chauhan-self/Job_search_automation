# Module 08: Pipeline Orchestrator

> **Depends on:** ALL other modules
> **Files to create:** `src/orchestrator.py`, `src/main.py`
> **External dependency:** None directly (coordinates other modules)
> **LLM required:** No
> **Estimated effort:** Small

---

## Purpose

The Orchestrator is the central coordinator of the system. It connects the loosely coupled modules by reading the database state and triggering the appropriate module. It manages the run lifecycle (starting a run, updating status, handling global errors) and is called by both the CLI and the Dashboard API.

---

## Input

- Config files (YAML) loaded via `src/config_loader.py`
- Database session

## Output

- A coordinated pipeline run executing Discovery → Scoring → Resume Generation
- Updates `runs` table status (`RUNNING` → `COMPLETED` or `FAILED`)

---

## File: `src/orchestrator.py`

### Class: `PipelineOrchestrator`

```python
import logging
from .database.connection import get_db
from .config_loader import load_config, load_profile, load_search_filters, load_answers
from .llm.client import LLMClient
from .discovery.engine import DiscoveryEngine
from .scoring.engine import ScoringEngine
from .resume_factory.tailoring import ResumeTailor
from .resume_factory.renderer import ResumeRenderer

class PipelineOrchestrator:
    def __init__(self):
        self.db = get_db()
        self.config = load_config()
        self.profile = load_profile()
        self.search_filters = load_search_filters()
        self.answers = load_answers()
        
        # Initialize LLM Client (shared)
        from .config_loader import load_secrets
        self.secrets = load_secrets()
        self.llm_client = LLMClient(self.db, self.config, self.secrets)

    async def start_run(self) -> str:
        """
        Main entry point for a pipeline run.
        Returns: run_id (UUID)
        
        Execution Flow:
        1. Create new row in `runs` table (status="RUNNING")
        2. Try:
             a. Run DiscoveryEngine
             b. Run ScoringEngine
             c. Run ResumeFactory
           Except:
             Update run status="FAILED", log error
        3. Update run status="COMPLETED"
        4. Calculate total cost and update run record
        """
        ...

    async def _run_phase_discovery(self, run_id: str):
        """Initialize and run DiscoveryEngine"""
        engine = DiscoveryEngine(self.db, self.config, self.search_filters, self.profile)
        jobs_found = engine.run(run_id)
        # Update runs table
        ...

    async def _run_phase_scoring(self, run_id: str):
        """Initialize and run ScoringEngine"""
        engine = ScoringEngine(self.db, self.llm_client, self.config, self.profile)
        stats = engine.run(run_id)
        # Update runs table
        ...

    async def _run_phase_resume_generation(self, run_id: str):
        """
        Initialize ResumeTailor and ResumeRenderer.
        Query jobs WHERE status = "SCORED" AND run_id = run_id.
        For each job:
          - Generate tailored content (Tailor)
          - Render PDF (Renderer)
          - Update DB status -> RESUME_READY or QUEUED_FOR_MANUAL
        """
        ...
```

---

## Important Distinction: What the Orchestrator DOES NOT do

Notice that the Orchestrator **does not run the Auto-Applier**.

Why? Because of the **Human Review Gate** introduced in the design audit.

1. The Orchestrator stops after `RESUME_READY` (or `REVIEW_QUEUED` for LinkedIn jobs).
2. The user goes to the Dashboard, reviews the "Review & Launch" queue, and clicks "Apply All".
3. The Dashboard API directly triggers the `AutoApplier` class for the approved jobs.

---

## File: `src/main.py` (CLI Entry Point)

```python
import argparse
import asyncio
import sys
from src.orchestrator import PipelineOrchestrator
from src.dashboard.app import app
import uvicorn

def run_pipeline():
    print("Starting job search pipeline...")
    orchestrator = PipelineOrchestrator()
    asyncio.run(orchestrator.start_run())
    print("Pipeline completed. Open the dashboard to review and apply.")

def start_dashboard(port: int = 8000):
    print(f"Starting dashboard on http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Search Automation")
    parser.add_argument("command", choices=["run", "dashboard"], 
                        help="Command to execute")
    parser.add_argument("--port", type=int, default=8000, 
                        help="Port for the dashboard")
    
    args = parser.parse_args()
    
    if args.command == "run":
        run_pipeline()
    elif args.command == "dashboard":
        start_dashboard(args.port)
```

---

## Error Handling

- **Global Try/Catch:** The `start_run()` method wraps the entire phase execution in a try/except block.
- **Fail Gracefully:** If an unhandled exception bubbles up from a module (e.g., SQLite connection loss), the orchestrator catches it, updates the `runs` table to `FAILED`, saves the traceback to `error_log`, and exits cleanly.
- **Phase Isolation:** A failure in Scoring shouldn't break the discovery data that was already saved. Because modules write state to SQLite immediately, the pipeline is resumable on the next run.

---

## Test Scenarios (`tests/test_orchestrator.py`)

1. **Test successful run:** Mock the engines (Discovery, Scoring, Resume) and verify they are called in the correct order, and run status transitions `RUNNING` → `COMPLETED`.
2. **Test error handling:** Mock `ScoringEngine` to throw an unhandled exception. Verify run status becomes `FAILED` and error log is saved.
3. **Test run state recording:** Verify that `jobs_discovered` and `jobs_scored` values returned by the engines are correctly written to the `runs` table.
