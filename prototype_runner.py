import sys
import subprocess
import time
import threading
import uvicorn
import logging
from src.discovery.engine import DiscoveryEngine
from src.database.connection import get_db
from src.config_loader import load_config, load_search_filters, load_profile

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_dashboard():
    logger.info("Starting Unified Dashboard on http://localhost:8000...")
    uvicorn.run("src.dashboard.app:app", host="127.0.0.1", port=8000, log_level="error")

def run_jobspy_discovery():
    logger.info("Running JobSpy discovery for non-LinkedIn jobs...")
    db = get_db()
    discovery = DiscoveryEngine(db, load_config(), load_search_filters(), load_profile())
    found = discovery.run(run_id="prototype-run")
    logger.info(f"JobSpy discovered {found} jobs.")
    return found

def run_aihawk():
    logger.info("Launching AIHawk Auto-Applier for LinkedIn...")
    try:
        # Launching the authentic AIHawk engine with the active Python runtime
        process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd="aihawk_core/Jobs_Applier_AI_Agent_AIHawk-main"
        )
        process.wait()
    except Exception as e:
        logger.error(f"Failed to launch AIHawk: {e}")
    except Exception as e:
        logger.error(f"Failed to launch AIHawk: {e}")

def run_aihawk_sync():
    while True:
        try:
            from src.dashboard.aihawk_sync import sync_aihawk_jobs
            sync_aihawk_jobs("aihawk_core/Jobs_Applier_AI_Agent_AIHawk-main/job_applications")
        except Exception as e:
            logger.error(f"Sync error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    # 1. Start dashboard in a background thread
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    
    # 2. Give dashboard time to start
    time.sleep(1)
    
    # 3. Discover external jobs via JobSpy in background
    discovery_thread = threading.Thread(target=run_jobspy_discovery, daemon=True)
    discovery_thread.start()
    
    # 4. Start AIHawk Sync thread in background
    logger.info("Starting AIHawk Output Sync background thread...")
    sync_thread = threading.Thread(target=run_aihawk_sync, daemon=True)
    sync_thread.start()
    
    # 5. Start AIHawk for LinkedIn auto-applying
    logger.info("Starting AIHawk Engine...")
    run_aihawk()
    
    logger.info("Prototype runner finished. Dashboard remains active.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
