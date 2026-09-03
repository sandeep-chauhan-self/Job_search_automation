"""Corpus operations shared by the pipeline and the API.

Status changes and document generation must record history from every call
site, so both go through here rather than being written inline.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src import constants as C
from src.database.models import Document, Interview, Job, JobEvent


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_event(
    db: Session,
    job_id: str,
    event_type: str,
    summary: str,
    detail: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    commit: bool = True,
) -> JobEvent:
    event = JobEvent(
        job_id=job_id,
        event_type=event_type,
        summary=summary,
        detail=detail,
        from_status=from_status,
        to_status=to_status,
    )
    db.add(event)
    if commit:
        db.commit()
    return event


def change_status(
    db: Session,
    job: Job,
    new_status: str,
    reason: str | None = None,
    method: str | None = None,
    commit: bool = True,
) -> Job:
    """Single funnel for status transitions so the timeline can never miss one."""
    old_status = job.status
    if old_status == new_status and not reason:
        return job

    job.status = new_status
    job.last_status_change_at = utcnow()

    if new_status in C.POST_APPLY_STATUSES and not job.applied_at:
        job.applied_at = utcnow()
        job.applied_method = method or job.applied_method or "manual"

    # Chasing a dead application wastes time; clear the reminder when it closes.
    if new_status in C.CLOSED_STATUSES:
        job.follow_up_at = None

    record_event(
        db,
        job.id,
        C.EVENT_STATUS_CHANGED,
        summary=f"{old_status} -> {new_status}",
        detail=reason,
        from_status=old_status,
        to_status=new_status,
        commit=False,
    )

    if commit:
        db.commit()
    return job


def register_document(
    db: Session,
    job: Job,
    kind: str,
    file_path: str,
    content: dict | str | None = None,
    model_used: str | None = None,
    commit: bool = True,
) -> Document:
    """Version documents per job so regenerating never loses the previous copy."""
    previous = (
        db.query(Document)
        .filter(Document.job_id == job.id, Document.kind == kind)
        .order_by(Document.version.desc())
        .all()
    )
    for doc in previous:
        doc.is_current = False

    snapshot = None
    if content is not None:
        snapshot = content if isinstance(content, str) else json.dumps(content, default=str)

    document = Document(
        job_id=job.id,
        kind=kind,
        version=(previous[0].version + 1) if previous else 1,
        file_path=file_path,
        content_snapshot=snapshot,
        model_used=model_used,
    )
    db.add(document)

    if kind == C.DOCUMENT_RESUME:
        job.resume_path = file_path
        job.resume_generated_at = utcnow()
    else:
        job.cover_letter_path = file_path

    record_event(
        db,
        job.id,
        C.EVENT_DOCUMENT_GENERATED,
        summary=f"{kind.replace('_', ' ').title()} v{document.version} generated",
        detail=os.path.basename(file_path),
        commit=False,
    )

    if commit:
        db.commit()
    return document


def set_follow_up(db: Session, job: Job, when: datetime | None, note: str | None = None) -> Job:
    job.follow_up_at = when
    record_event(
        db,
        job.id,
        C.EVENT_FOLLOW_UP,
        summary=f"Follow-up set for {when.date()}" if when else "Follow-up cleared",
        detail=note,
        commit=False,
    )
    db.commit()
    return job


def needs_attention(db: Session, stale_after_days: int = 10) -> dict:
    """Everything asking for action today, so nothing quietly rots in the pipeline."""
    now = utcnow()

    due_follow_ups = (
        db.query(Job)
        .filter(Job.follow_up_at.isnot(None), Job.follow_up_at <= now, Job.archived_at.is_(None))
        .order_by(Job.follow_up_at)
        .all()
    )

    upcoming_interviews = (
        db.query(Interview)
        .filter(
            Interview.scheduled_at.isnot(None),
            Interview.scheduled_at >= now,
            Interview.outcome == "SCHEDULED",
        )
        .order_by(Interview.scheduled_at)
        .limit(25)
        .all()
    )

    closing_soon = (
        db.query(Job)
        .filter(
            Job.deadline_at.isnot(None),
            Job.deadline_at >= now,
            Job.deadline_at <= now + timedelta(days=7),
            Job.status.notin_(C.POST_APPLY_STATUSES + C.CLOSED_STATUSES),
        )
        .order_by(Job.deadline_at)
        .all()
    )

    stale = (
        db.query(Job)
        .filter(
            Job.status.in_(C.ACTIVE_PURSUIT_STATUSES),
            Job.applied_at.isnot(None),
            Job.applied_at <= now - timedelta(days=stale_after_days),
            Job.archived_at.is_(None),
        )
        .order_by(Job.applied_at)
        .all()
    )

    ready_to_apply = (
        db.query(Job)
        .filter(Job.status == C.STATUS_RESUME_READY, Job.archived_at.is_(None))
        .order_by(Job.match_score.desc())
        .all()
    )

    return {
        "due_follow_ups": due_follow_ups,
        "upcoming_interviews": upcoming_interviews,
        "closing_soon": closing_soon,
        "stale_applications": stale,
        "ready_to_apply": ready_to_apply,
    }
