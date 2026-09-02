import os
import json
import logging
from sqlalchemy.orm import Session
import hashlib
from src.database.connection import get_db
from src.database.models import Job
from datetime import datetime

logger = logging.getLogger(__name__)

def sync_aihawk_jobs(applications_dir: str):
    db: Session = get_db()
    
    if not os.path.exists(applications_dir):
        logger.warning(f"AIHawk applications directory {applications_dir} does not exist yet.")
        return

    for folder_name in os.listdir(applications_dir):
        folder_path = os.path.join(applications_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
            
        desc_file = os.path.join(folder_path, "job_description.json")
        app_file = os.path.join(folder_path, "job_application.json")
        
        if os.path.exists(desc_file):
            with open(desc_file, 'r', encoding='utf-8') as f:
                try:
                    job_data = json.load(f)
                except Exception as e:
                    logger.error(f"Error reading {desc_file}: {e}")
                    continue
            
            # Create a unique hash for deduplication
            url = job_data.get("link", "")
            dedup_hash = hashlib.md5(url.encode()).hexdigest() if url else folder_name
            
            # Check if job already exists in DB
            existing_job = db.query(Job).filter_by(dedup_hash=dedup_hash).first()
            if not existing_job:
                new_job = Job(
                    title=job_data.get("title", "Unknown"),
                    company=job_data.get("company", "Unknown"),
                    location=job_data.get("location", "Unknown"),
                    platform="LinkedIn",
                    job_url=url,
                    description=job_data.get("description", ""),
                    dedup_hash=dedup_hash,
                    status="AUTO_APPLIED" if os.path.exists(app_file) else "DISCOVERED",
                    applied_at=datetime.utcnow() if os.path.exists(app_file) else None,
                    applied_method="AIHawk",
                    resume_path=os.path.join(folder_path, "resume.pdf") if os.path.exists(os.path.join(folder_path, "resume.pdf")) else None,
                    cover_letter_path=os.path.join(folder_path, "cover_letter.pdf") if os.path.exists(os.path.join(folder_path, "cover_letter.pdf")) else None
                )
                db.add(new_job)
                logger.info(f"Synced AIHawk job: {new_job.title} at {new_job.company}")
            else:
                # Update status if applied
                if os.path.exists(app_file) and existing_job.status != "AUTO_APPLIED":
                    existing_job.status = "AUTO_APPLIED"
                    existing_job.applied_at = datetime.utcnow()
                    existing_job.applied_method = "AIHawk"
                    logger.info(f"Updated status for AIHawk job: {existing_job.title}")

    db.commit()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_aihawk_jobs("aihawk_core/Jobs_Applier_AI_Agent_AIHawk-main/job_applications")
