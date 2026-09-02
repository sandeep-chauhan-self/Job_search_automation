from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from src.database.connection import get_db_context
from src.database.models import Job, Run, LLMUsage
from sqlalchemy import desc, func
import os

router = APIRouter()

@router.get("/jobs")
async def list_jobs(
    status: str = None,
    platform: str = None,
    min_score: int = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db_context)
):
    query = db.query(Job)
    
    if status:
        query = query.filter(Job.status == status)
    if platform:
        query = query.filter(Job.platform == platform)
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)
        
    total = query.count()
    
    jobs = query.order_by(desc(Job.discovered_at)).offset((page - 1) * page_size).limit(page_size).all()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "jobs": [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "platform": j.platform,
                "status": j.status,
                "match_score": j.match_score,
                "discovered_at": j.discovered_at,
                "job_url": j.job_url
            } for j in jobs
        ]
    }

@router.patch("/jobs/{job_id}/status")
async def update_job_status(job_id: str, status: str, db: Session = Depends(get_db_context)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job.status = status
    db.commit()
    return {"status": "updated"}

@router.get("/analytics/summary")
async def get_analytics(db: Session = Depends(get_db_context)):
    total_applied = db.query(Job).filter(Job.status == "APPLIED").count()
    total_ghosted = db.query(Job).filter(Job.status == "GHOSTED").count()
    
    platforms_query = db.query(Job.platform, func.count(Job.id)).group_by(Job.platform).all()
    apps_by_platform = {k: v for k, v in platforms_query}
    
    avg_score = db.query(func.avg(Job.match_score)).filter(Job.status == "APPLIED").scalar()
    
    return {
        "total_applied": total_applied,
        "total_ghosted": total_ghosted,
        "apps_by_platform": apps_by_platform,
        "avg_match_score": round(avg_score or 0, 2)
    }

@router.post("/cron/ghosting-check")
async def run_ghosting_check(db: Session = Depends(get_db_context)):
    # Very simple ghosting check, mark APPLIED -> GHOSTED if older than 14 days
    import datetime
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=14)
    jobs = db.query(Job).filter(Job.status == "APPLIED", Job.applied_at < cutoff).all()
    count = 0
    for j in jobs:
        j.status = "GHOSTED"
        count += 1
    db.commit()
    return {"ghosted_count": count}
