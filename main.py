import argparse
import asyncio
import logging
import uvicorn
from src.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(description="Job Search Automation CLI")
    parser.add_argument("command", choices=["discover", "dashboard", "apply"], help="Command to run")
    parser.add_argument("--job-ids", help="Comma-separated job IDs for apply command", default="")
    
    args = parser.parse_args()
    
    if args.command == "discover":
        orchestrator = Orchestrator()
        orchestrator.run_pipeline()
        
    elif args.command == "dashboard":
        logging.info("Starting dashboard on http://localhost:8000")
        uvicorn.run("src.dashboard.app:app", host="0.0.0.0", port=8000, reload=False)
        
    elif args.command == "apply":
        if not args.job_ids:
            logging.error("Must provide --job-ids for apply command")
            return
        job_ids = [j.strip() for j in args.job_ids.split(",")]
        orchestrator = Orchestrator()
        asyncio.run(orchestrator.run_apply(job_ids))

if __name__ == "__main__":
    main()
