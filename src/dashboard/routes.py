import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.config_loader import load_config
from src.database.connection import get_db_context
from src.database.models import Job, LLMUsage, Run
from src.dashboard.run_manager import run_manager

router = APIRouter()

ALLOWED_STATUSES = {
    "DISCOVERED",
    "SCORED",
    "SKIPPED",
    "APPROVED",
    "RESUME_READY",
    "APPLIED",
    "QUEUED_FOR_MANUAL",
    "REJECTED",
    "INTERVIEW",
    "OFFER",
    "GHOSTED",
}

FUNNEL_ORDER = [
    "DISCOVERED",
    "SCORED",
    "APPROVED",
    "RESUME_READY",
    "APPLIED",
    "INTERVIEW",
    "OFFER",
]

OUTPUT_ROOT = os.path.abspath("output")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [str(parsed)]
    except (json.JSONDecodeError, TypeError):
        return []


def _job_summary(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "platform": job.platform,
        "status": job.status,
        "match_score": job.match_score,
        "salary_info": job.salary_info,
        "work_mode": job.work_mode,
        "discovered_at": _iso(job.discovered_at),
        "applied_at": _iso(job.applied_at),
        "job_url": job.job_url,
        "has_resume": bool(job.resume_path),
        "has_cover_letter": bool(job.cover_letter_path),
    }


# -- jobs --------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    platform: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
    sort: str = Query("discovered_at", pattern="^(discovered_at|match_score|company|applied_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_context),
):
    query = db.query(Job)

    if status:
        statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
        query = query.filter(Job.status.in_(statuses))
    if platform:
        query = query.filter(Job.platform == platform)
    if min_score is not None:
        query = query.filter(Job.match_score >= min_score)
    if search:
        pattern = f"%{search}%"
        query = query.filter((Job.title.ilike(pattern)) | (Job.company.ilike(pattern)))

    total = query.count()

    column = getattr(Job, sort)
    query = query.order_by(desc(column) if order == "desc" else column)

    jobs = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "jobs": [_job_summary(j) for j in jobs],
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: Session = Depends(get_db_context)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cost = db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.job_id == job_id).scalar() or 0.0

    detail = _job_summary(job)
    detail.update(
        description=job.description or "",
        match_reasons=_parse_json_list(job.match_reasons),
        match_gaps=_parse_json_list(job.match_gaps),
        notes=job.notes,
        applied_method=job.applied_method,
        scored_at=_iso(job.scored_at),
        resume_generated_at=_iso(job.resume_generated_at),
        llm_cost_usd=round(cost, 4),
    )
    return detail


@router.patch("/jobs/{job_id}/status")
async def update_job_status(
    job_id: str,
    status: str = Body(..., embed=True),
    db: Session = Depends(get_db_context),
):
    new_status = status.strip().upper()
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {sorted(ALLOWED_STATUSES)}")

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = new_status
    if new_status == "APPLIED" and not job.applied_at:
        job.applied_at = _utcnow()
        job.applied_method = "manual"
    db.commit()
    return {"id": job.id, "status": job.status}


@router.post("/jobs/bulk-status")
async def bulk_update_status(
    job_ids: list[str] = Body(...),
    status: str = Body(...),
    db: Session = Depends(get_db_context),
):
    new_status = status.strip().upper()
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {sorted(ALLOWED_STATUSES)}")

    updated = db.query(Job).filter(Job.id.in_(job_ids)).update(
        {Job.status: new_status}, synchronize_session=False
    )
    db.commit()
    return {"updated": updated, "status": new_status}


@router.get("/jobs/{job_id}/document/{kind}")
async def download_document(job_id: str, kind: str, db: Session = Depends(get_db_context)):
    if kind not in ("resume", "cover_letter"):
        raise HTTPException(status_code=422, detail="kind must be 'resume' or 'cover_letter'")

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = job.resume_path if kind == "resume" else job.cover_letter_path
    if not path:
        raise HTTPException(status_code=404, detail=f"No {kind} generated for this job")

    # Confine downloads to output/ so a tampered DB path cannot read arbitrary files.
    resolved = os.path.abspath(path)
    if os.path.commonpath([resolved, OUTPUT_ROOT]) != OUTPUT_ROOT or not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail="Document file is missing")

    return FileResponse(resolved, media_type="application/pdf", filename=os.path.basename(resolved))


# -- runs --------------------------------------------------------------------


@router.get("/runs/current")
async def current_run():
    return run_manager.snapshot()


@router.get("/runs/logs")
async def run_logs(after: int = 0):
    return {"logs": run_manager.logs_since(after)}


@router.get("/runs/stream")
async def run_stream():
    return StreamingResponse(
        run_manager.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/discover")
async def start_discovery():
    from src.orchestrator import run_discovery_job

    ok, message = run_manager.start("discover", run_discovery_job)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"started": True}


@router.post("/runs/prepare")
async def start_prepare(job_ids: list[str] = Body(..., embed=True)):
    from src.orchestrator import run_prepare_job

    if not job_ids:
        raise HTTPException(status_code=422, detail="job_ids must not be empty")
    ok, message = run_manager.start("prepare", run_prepare_job, job_ids)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"started": True, "count": len(job_ids)}


@router.post("/runs/apply")
async def start_apply(job_ids: list[str] = Body(..., embed=True)):
    from src.orchestrator import run_apply_job

    if not job_ids:
        raise HTTPException(status_code=422, detail="job_ids must not be empty")
    ok, message = run_manager.start("apply", run_apply_job, job_ids)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"started": True, "count": len(job_ids)}


@router.post("/runs/cancel")
async def cancel_run():
    if not run_manager.request_cancel():
        raise HTTPException(status_code=409, detail="No run is currently active.")
    return {"cancelling": True}


@router.get("/runs/history")
async def run_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db_context)):
    runs = db.query(Run).order_by(desc(Run.started_at)).limit(limit).all()
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "started_at": _iso(r.started_at),
                "completed_at": _iso(r.completed_at),
                "jobs_discovered": r.jobs_discovered,
                "jobs_scored": r.jobs_scored,
                "jobs_above_threshold": r.jobs_above_threshold,
                "auto_applied": r.auto_applied,
                "error_log": r.error_log,
            }
            for r in runs
        ]
    }


# -- analytics ---------------------------------------------------------------


def _cumulative_funnel(db: Session) -> list[dict]:
    """Count jobs that reached at least each stage.

    Status is a single current value, so counting it directly would show a job
    that is now APPLIED as no longer DISCOVERED. Persisted timestamps and paths
    give a truthful funnel instead.
    """
    reached_approved = ("APPROVED", "RESUME_READY", "APPLIED", "INTERVIEW", "OFFER")
    reached_resume = ("RESUME_READY", "APPLIED", "INTERVIEW", "OFFER")
    stages = [
        ("DISCOVERED", db.query(Job)),
        ("SCORED", db.query(Job).filter(Job.match_score.isnot(None))),
        ("APPROVED", db.query(Job).filter(Job.status.in_(reached_approved))),
        ("RESUME_READY", db.query(Job).filter(Job.resume_path.isnot(None) | Job.status.in_(reached_resume))),
        ("APPLIED", db.query(Job).filter(Job.applied_at.isnot(None) | Job.status.in_(("INTERVIEW", "OFFER")))),
        ("INTERVIEW", db.query(Job).filter(Job.status.in_(("INTERVIEW", "OFFER")))),
        ("OFFER", db.query(Job).filter(Job.status == "OFFER")),
    ]
    return [{"stage": name, "count": query.count()} for name, query in stages]


@router.get("/analytics/summary")
async def get_analytics(db: Session = Depends(get_db_context)):
    counts = dict(db.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
    platforms = dict(db.query(Job.platform, func.count(Job.id)).group_by(Job.platform).all())

    avg_score = db.query(func.avg(Job.match_score)).filter(Job.status == "APPLIED").scalar()
    total_cost = db.query(func.sum(LLMUsage.cost_usd)).scalar() or 0.0
    applied_today = (
        db.query(Job).filter(Job.status == "APPLIED", Job.applied_at >= _utcnow() - timedelta(days=1)).count()
    )

    config = load_config().get("application", {})

    return {
        "total_jobs": sum(counts.values()),
        "total_applied": counts.get("APPLIED", 0),
        "total_ghosted": counts.get("GHOSTED", 0),
        "status_counts": counts,
        "funnel": _cumulative_funnel(db),
        "apps_by_platform": platforms,
        "avg_match_score": round(avg_score or 0, 2),
        "total_llm_cost_usd": round(total_cost, 4),
        "applied_today": applied_today,
        "daily_limit": config.get("daily_limit", 25),
        "min_match_score": config.get("min_match_score", 60),
        "dry_run": config.get("dry_run", True),
    }


@router.post("/cron/ghosting-check")
async def run_ghosting_check(db: Session = Depends(get_db_context)):
    days = load_config().get("ghosting", {}).get("days_until_ghosted", 14)
    cutoff = _utcnow() - timedelta(days=days)
    ghosted = (
        db.query(Job)
        .filter(Job.status == "APPLIED", Job.applied_at.isnot(None), Job.applied_at < cutoff)
        .update({Job.status: "GHOSTED"}, synchronize_session=False)
    )
    db.commit()
    return {"ghosted_count": ghosted, "days_until_ghosted": days}
