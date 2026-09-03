import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from src import constants as C
from src import corpus
from src.config_loader import load_config, load_profile
from src.database.connection import get_db_context
from src.database.models import Contact, Document, Interview, Job, JobEvent, LLMUsage, Run
from src.dashboard.run_manager import run_manager
from src.settings import OUTPUT_DIR, settings

router = APIRouter()

ALLOWED_STATUSES = set(C.ALL_STATUSES)

FUNNEL_ORDER = C.FUNNEL_ORDER

OUTPUT_ROOT = os.path.abspath(OUTPUT_DIR)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid datetime: {value}")
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
        "is_favorite": bool(job.is_favorite),
        "priority": job.priority or 0,
        "follow_up_at": _iso(job.follow_up_at),
        "deadline_at": _iso(job.deadline_at),
        "tags": _parse_json_list(job.tags),
        "archived": bool(job.archived_at),
    }


# -- jobs --------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    platform: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
    favorite: bool | None = None,
    include_archived: bool = False,
    sort: str = Query("discovered_at", pattern="^(discovered_at|match_score|company|applied_at|priority|follow_up_at|deadline_at)$"),
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
    if favorite:
        query = query.filter(Job.is_favorite.is_(True))
    if not include_archived:
        query = query.filter(Job.archived_at.is_(None))
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Job.title.ilike(pattern), Job.company.ilike(pattern), Job.location.ilike(pattern))
        )

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
    job = _get_job_or_404(db, job_id)

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
        referral_name=job.referral_name,
        rejection_reason=job.rejection_reason,
        llm_cost_usd=round(cost, 4),
        events=[
            {
                "id": e.id,
                "type": e.event_type,
                "summary": e.summary,
                "detail": e.detail,
                "created_at": _iso(e.created_at),
            }
            for e in sorted(job.events, key=lambda e: e.created_at or _utcnow(), reverse=True)
        ],
        documents=[
            {
                "id": d.id,
                "kind": d.kind,
                "version": d.version,
                "is_current": d.is_current,
                "file_name": os.path.basename(d.file_path),
                "created_at": _iso(d.created_at),
            }
            for d in sorted(job.documents, key=lambda d: d.created_at or _utcnow(), reverse=True)
        ],
        interviews=[
            {
                "id": i.id,
                "round_name": i.round_name,
                "scheduled_at": _iso(i.scheduled_at),
                "mode": i.mode,
                "interviewer": i.interviewer,
                "outcome": i.outcome,
                "prep_notes": i.prep_notes,
                "feedback": i.feedback,
            }
            for i in job.interviews
        ],
        contacts=[
            {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "email": c.email,
                "phone": c.phone,
                "linkedin_url": c.linkedin_url,
                "notes": c.notes,
            }
            for c in job.contacts
        ],
    )
    return detail


@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db_context),
):
    """Update the tracking fields a job seeker maintains by hand."""
    job = _get_job_or_404(db, job_id)

    if "notes" in payload:
        job.notes = payload["notes"]
    if "is_favorite" in payload:
        job.is_favorite = bool(payload["is_favorite"])
    if "priority" in payload:
        job.priority = max(0, min(3, int(payload["priority"] or 0)))
    if "referral_name" in payload:
        job.referral_name = payload["referral_name"]
    if "rejection_reason" in payload:
        job.rejection_reason = payload["rejection_reason"]
    if "tags" in payload:
        tags = payload["tags"] or []
        job.tags = json.dumps([str(t) for t in tags])
    if "follow_up_at" in payload:
        corpus.set_follow_up(db, job, _parse_dt(payload["follow_up_at"]))
    if "deadline_at" in payload:
        job.deadline_at = _parse_dt(payload["deadline_at"])
    if "archived" in payload:
        job.archived_at = _utcnow() if payload["archived"] else None

    db.commit()
    return _job_summary(job)


@router.patch("/jobs/{job_id}/status")
async def update_job_status(
    job_id: str,
    status: str = Body(..., embed=True),
    reason: str | None = Body(None, embed=True),
    db: Session = Depends(get_db_context),
):
    new_status = status.strip().upper()
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {sorted(ALLOWED_STATUSES)}")

    job = _get_job_or_404(db, job_id)
    corpus.change_status(db, job, new_status, reason=reason)
    return {"id": job.id, "status": job.status}


@router.post("/jobs/{job_id}/notes")
async def add_note(
    job_id: str,
    note: str = Body(..., embed=True),
    db: Session = Depends(get_db_context),
):
    job = _get_job_or_404(db, job_id)
    corpus.record_event(db, job.id, C.EVENT_NOTE, "Note added", detail=note)
    return {"ok": True}


@router.post("/jobs/bulk-status")
async def bulk_update_status(
    job_ids: list[str] = Body(...),
    status: str = Body(...),
    db: Session = Depends(get_db_context),
):
    new_status = status.strip().upper()
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {sorted(ALLOWED_STATUSES)}")

    jobs = db.query(Job).filter(Job.id.in_(job_ids)).all()
    for job in jobs:
        corpus.change_status(db, job, new_status, commit=False)
    db.commit()
    return {"updated": len(jobs), "status": new_status}


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


@router.post("/runs/auto_apply")
async def start_auto_apply(job_ids: list[str] = Body(..., embed=True)):
    from src.orchestrator import run_auto_apply_job

    if not job_ids:
        raise HTTPException(status_code=422, detail="job_ids must not be empty")
    ok, message = run_manager.start("auto_apply", run_auto_apply_job, job_ids)
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


def _applied_filter():
    """A job counts as applied if it has a timestamp OR sits in a post-apply status.

    Rows imported by hand may carry the status without a timestamp, and rows from
    an older schema may predate the timestamp being set, so neither check alone
    is sufficient.
    """
    return or_(Job.applied_at.isnot(None), Job.status.in_(tuple(C.POST_APPLY_STATUSES)))


def _cumulative_funnel(db: Session) -> list[dict]:
    """Count jobs that reached at least each stage.

    Status is a single current value, so counting it directly would show a job
    that is now APPLIED as no longer DISCOVERED. Persisted timestamps and paths
    give a truthful funnel instead.
    """
    reached_shortlist = tuple(
        [C.STATUS_SHORTLISTED, C.STATUS_APPROVED, C.STATUS_RESUME_READY] + C.POST_APPLY_STATUSES
    )
    reached_resume = tuple([C.STATUS_RESUME_READY] + C.POST_APPLY_STATUSES)
    reached_interview = (C.STATUS_INTERVIEW, C.STATUS_OFFER)
    stages = [
        ("DISCOVERED", db.query(Job)),
        # A job can be shortlisted by hand without ever being scored, so status
        # has to count too or the funnel would report fewer scored than applied.
        (
            "SCORED",
            db.query(Job).filter(
                or_(Job.match_score.isnot(None), Job.status.in_(reached_shortlist))
            ),
        ),
        ("SHORTLISTED", db.query(Job).filter(Job.status.in_(reached_shortlist))),
        (
            "RESUME_READY",
            db.query(Job).filter(or_(Job.resume_path.isnot(None), Job.status.in_(reached_resume))),
        ),
        ("APPLIED", db.query(Job).filter(_applied_filter())),
        ("INTERVIEW", db.query(Job).filter(Job.status.in_(reached_interview))),
        ("OFFER", db.query(Job).filter(Job.status == C.STATUS_OFFER)),
    ]
    return [{"stage": name, "count": query.count()} for name, query in stages]


@router.get("/analytics/summary")
async def get_analytics(db: Session = Depends(get_db_context)):
    counts = dict(db.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
    platforms = dict(db.query(Job.platform, func.count(Job.id)).group_by(Job.platform).all())

    avg_score = db.query(func.avg(Job.match_score)).filter(_applied_filter()).scalar()
    total_cost = db.query(func.sum(LLMUsage.cost_usd)).scalar() or 0.0
    applied_today = db.query(Job).filter(Job.applied_at >= _utcnow() - timedelta(days=1)).count()

    applied_total = db.query(Job).filter(_applied_filter()).count()
    interview_total = db.query(Job).filter(Job.status.in_((C.STATUS_INTERVIEW, C.STATUS_OFFER))).count()

    config = load_config().get("application", {})

    return {
        "total_jobs": sum(counts.values()),
        "total_applied": applied_total,
        "total_ghosted": counts.get(C.STATUS_GHOSTED, 0),
        "status_counts": counts,
        "funnel": _cumulative_funnel(db),
        "apps_by_platform": platforms,
        "avg_match_score": round(avg_score or 0, 2),
        "total_llm_cost_usd": round(total_cost, 4),
        "applied_today": applied_today,
        "daily_limit": settings.daily_limit,
        "min_match_score": config.get("min_match_score", 60),
        "dry_run": settings.dry_run,
        "llm_configured": settings.is_llm_configured(),
        "interview_rate": round(100 * interview_total / applied_total, 1) if applied_total else 0.0,
        "response_rate": round(
            100
            * db.query(Job)
            .filter(_applied_filter(), Job.status.notin_([C.STATUS_APPLIED, C.STATUS_GHOSTED]))
            .count()
            / applied_total,
            1,
        )
        if applied_total
        else 0.0,
    }


@router.post("/cron/ghosting-check")
async def run_ghosting_check(db: Session = Depends(get_db_context)):
    days = load_config().get("ghosting", {}).get("days_until_ghosted", 14)
    cutoff = _utcnow() - timedelta(days=days)
    stale = (
        db.query(Job)
        .filter(Job.status == C.STATUS_APPLIED, Job.applied_at.isnot(None), Job.applied_at < cutoff)
        .all()
    )
    for job in stale:
        corpus.change_status(
            db, job, C.STATUS_GHOSTED, reason=f"No response for {days} days", commit=False
        )
    db.commit()
    return {"ghosted_count": len(stale), "days_until_ghosted": days}


# -- daily dashboard ---------------------------------------------------------


@router.get("/dashboard/today")
async def today_dashboard(db: Session = Depends(get_db_context)):
    """The single 'what do I need to do right now' view."""
    buckets = corpus.needs_attention(db, settings.stale_after_days)

    def job_line(job: Job) -> dict:
        return {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "status": job.status,
            "match_score": job.match_score,
            "follow_up_at": _iso(job.follow_up_at),
            "deadline_at": _iso(job.deadline_at),
            "applied_at": _iso(job.applied_at),
        }

    interviews = []
    for iv in buckets["upcoming_interviews"]:
        job = db.query(Job).filter(Job.id == iv.job_id).first()
        interviews.append(
            {
                "id": iv.id,
                "job_id": iv.job_id,
                "company": job.company if job else "unknown",
                "title": job.title if job else "unknown",
                "round_name": iv.round_name,
                "scheduled_at": _iso(iv.scheduled_at),
                "mode": iv.mode,
                "prep_notes": iv.prep_notes,
            }
        )

    return {
        "due_follow_ups": [job_line(j) for j in buckets["due_follow_ups"]],
        "upcoming_interviews": interviews,
        "closing_soon": [job_line(j) for j in buckets["closing_soon"]],
        "stale_applications": [job_line(j) for j in buckets["stale_applications"]],
        "ready_to_apply": [job_line(j) for j in buckets["ready_to_apply"]],
    }


# -- interviews --------------------------------------------------------------


@router.post("/jobs/{job_id}/interviews")
async def add_interview(job_id: str, payload: dict = Body(...), db: Session = Depends(get_db_context)):
    job = _get_job_or_404(db, job_id)

    interview = Interview(
        job_id=job.id,
        round_name=payload.get("round_name") or "Interview",
        scheduled_at=_parse_dt(payload.get("scheduled_at")),
        duration_minutes=payload.get("duration_minutes"),
        interviewer=payload.get("interviewer"),
        mode=payload.get("mode"),
        outcome=payload.get("outcome") or "SCHEDULED",
        prep_notes=payload.get("prep_notes"),
    )
    db.add(interview)

    if job.status not in (C.STATUS_INTERVIEW, C.STATUS_OFFER):
        corpus.change_status(db, job, C.STATUS_INTERVIEW, reason=f"{interview.round_name} scheduled", commit=False)

    corpus.record_event(
        db, job.id, C.EVENT_INTERVIEW, f"{interview.round_name} scheduled",
        detail=payload.get("scheduled_at"), commit=False,
    )
    db.commit()
    return {"id": interview.id}


@router.patch("/interviews/{interview_id}")
async def update_interview(interview_id: str, payload: dict = Body(...), db: Session = Depends(get_db_context)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    for field in ("round_name", "interviewer", "mode", "prep_notes", "feedback"):
        if field in payload:
            setattr(interview, field, payload[field])
    if "scheduled_at" in payload:
        interview.scheduled_at = _parse_dt(payload["scheduled_at"])
    if "outcome" in payload:
        outcome = str(payload["outcome"]).upper()
        if outcome not in C.INTERVIEW_OUTCOMES:
            raise HTTPException(status_code=422, detail=f"Allowed outcomes: {C.INTERVIEW_OUTCOMES}")
        interview.outcome = outcome
        corpus.record_event(
            db, interview.job_id, C.EVENT_INTERVIEW,
            f"{interview.round_name}: {outcome}", detail=payload.get("feedback"), commit=False,
        )

    db.commit()
    return {"ok": True}


@router.delete("/interviews/{interview_id}")
async def delete_interview(interview_id: str, db: Session = Depends(get_db_context)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(interview)
    db.commit()
    return {"ok": True}


@router.get("/interviews")
async def list_interviews(upcoming_only: bool = False, db: Session = Depends(get_db_context)):
    query = db.query(Interview)
    if upcoming_only:
        query = query.filter(Interview.scheduled_at >= _utcnow(), Interview.outcome == "SCHEDULED")

    rows = []
    for iv in query.order_by(Interview.scheduled_at.desc()).limit(200).all():
        job = db.query(Job).filter(Job.id == iv.job_id).first()
        rows.append(
            {
                "id": iv.id,
                "job_id": iv.job_id,
                "company": job.company if job else "unknown",
                "title": job.title if job else "unknown",
                "round_name": iv.round_name,
                "scheduled_at": _iso(iv.scheduled_at),
                "mode": iv.mode,
                "interviewer": iv.interviewer,
                "outcome": iv.outcome,
                "feedback": iv.feedback,
            }
        )
    return {"interviews": rows}


# -- contacts ----------------------------------------------------------------


@router.post("/jobs/{job_id}/contacts")
async def add_contact(job_id: str, payload: dict = Body(...), db: Session = Depends(get_db_context)):
    job = _get_job_or_404(db, job_id)
    if not payload.get("name"):
        raise HTTPException(status_code=422, detail="Contact name is required")

    contact = Contact(
        job_id=job.id,
        name=payload["name"],
        role=payload.get("role"),
        email=payload.get("email"),
        phone=payload.get("phone"),
        linkedin_url=payload.get("linkedin_url"),
        notes=payload.get("notes"),
    )
    db.add(contact)
    corpus.record_event(
        db, job.id, C.EVENT_CONTACT, f"Contact added: {contact.name}",
        detail=contact.role, commit=False,
    )
    db.commit()
    return {"id": contact.id}


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, db: Session = Depends(get_db_context)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"ok": True}


# -- document library --------------------------------------------------------


@router.get("/documents")
async def list_documents(
    kind: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_context),
):
    query = db.query(Document)
    if kind:
        query = query.filter(Document.kind == kind)

    total = query.count()
    docs = (
        query.order_by(desc(Document.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    )

    rows = []
    for d in docs:
        job = db.query(Job).filter(Job.id == d.job_id).first()
        rows.append(
            {
                "id": d.id,
                "job_id": d.job_id,
                "company": job.company if job else None,
                "title": job.title if job else None,
                "kind": d.kind,
                "version": d.version,
                "is_current": d.is_current,
                "file_name": os.path.basename(d.file_path),
                "exists": os.path.exists(d.file_path),
                "created_at": _iso(d.created_at),
            }
        )
    return {"total": total, "page": page, "pages": max(1, -(-total // page_size)), "documents": rows}


@router.get("/documents/{document_id}/download")
async def download_versioned_document(document_id: str, db: Session = Depends(get_db_context)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    resolved = os.path.abspath(doc.file_path)
    if os.path.commonpath([resolved, OUTPUT_ROOT]) != OUTPUT_ROOT or not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail="Document file is missing")
    return FileResponse(resolved, media_type="application/pdf", filename=os.path.basename(resolved))


# -- assistant ---------------------------------------------------------------


@router.get("/profile/status")
async def profile_status(db: Session = Depends(get_db_context)):
    from src.assistant import ProfileAssistant

    assistant = ProfileAssistant(db, None, load_profile())
    return assistant.profile_completeness()


@router.post("/assistant/ask")
async def assistant_ask(question: str = Body(..., embed=True), db: Session = Depends(get_db_context)):
    if not question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty")
    if not settings.is_llm_configured():
        raise HTTPException(status_code=409, detail="No LLM API key configured.")

    from src.assistant import ProfileAssistant
    from src.config_loader import load_secrets
    from src.llm.client import LLMClient

    llm = LLMClient(db, load_config(), load_secrets())
    assistant = ProfileAssistant(db, llm, load_profile())
    result = assistant.ask(question.strip())
    if result["error"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


# -- export ------------------------------------------------------------------


@router.get("/export/jobs.csv")
async def export_jobs_csv(db: Session = Depends(get_db_context)):
    """Own your data - a spreadsheet you can keep regardless of this app."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "company", "title", "location", "platform", "status", "match_score",
        "salary", "work_mode", "discovered_at", "applied_at", "follow_up_at",
        "deadline_at", "priority", "favorite", "referral", "notes", "url",
    ])
    for job in db.query(Job).order_by(desc(Job.discovered_at)).all():
        writer.writerow([
            job.company, job.title, job.location, job.platform, job.status,
            job.match_score, job.salary_info, job.work_mode,
            job.discovered_at, job.applied_at, job.follow_up_at, job.deadline_at,
            job.priority, job.is_favorite, job.referral_name,
            (job.notes or "").replace("\n", " "), job.job_url,
        ])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=job_corpus.csv"},
    )


@router.get("/settings")
async def get_settings():
    return settings.as_dict()
