import uuid
import datetime
from sqlalchemy import Boolean, Column, String, Integer, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

class Run(Base):
    __tablename__ = 'runs'
    id = Column(String, primary_key=True, default=generate_uuid)
    started_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String, default="RUNNING")  # RUNNING, COMPLETED, FAILED
    jobs_discovered = Column(Integer, default=0)
    jobs_scored = Column(Integer, default=0)
    jobs_above_threshold = Column(Integer, default=0)
    resumes_generated = Column(Integer, default=0)
    auto_applied = Column(Integer, default=0)
    queued_for_manual = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    total_llm_cost = Column(Float, default=0.0)
    error_log = Column(Text, nullable=True)

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(String, primary_key=True, default=generate_uuid)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, nullable=True)
    platform = Column(String, nullable=False)
    job_url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    dedup_hash = Column(String, unique=True, nullable=False)
    status = Column(String, default="DISCOVERED", index=True)
    match_score = Column(Integer, nullable=True, index=True)
    match_reasons = Column(Text, nullable=True) # JSON string
    match_gaps = Column(Text, nullable=True) # JSON string
    resume_path = Column(String, nullable=True)
    cover_letter_path = Column(String, nullable=True)
    salary_info = Column(String, nullable=True)
    work_mode = Column(String, nullable=True)
    discovered_at = Column(DateTime, default=utcnow, index=True)
    scored_at = Column(DateTime, nullable=True)
    resume_generated_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True, index=True)
    applied_method = Column(String, nullable=True)
    run_id = Column(String, ForeignKey('runs.id'), nullable=True)
    notes = Column(Text, nullable=True)

    # -- job-seeker corpus fields -------------------------------------------
    is_favorite = Column(Boolean, default=False)
    priority = Column(Integer, default=0)          # 0 none, 1 low, 2 medium, 3 high
    follow_up_at = Column(DateTime, nullable=True) # when to chase this up
    deadline_at = Column(DateTime, nullable=True)  # posting closes
    referral_name = Column(String, nullable=True)  # who can refer me
    rejection_reason = Column(Text, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    last_status_change_at = Column(DateTime, nullable=True)
    tags = Column(Text, nullable=True)             # JSON list of free-form labels

    events = relationship(
        "JobEvent", back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.created_at"
    )
    documents = relationship("Document", back_populates="job", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="job", cascade="all, delete-orphan")
    interviews = relationship(
        "Interview", back_populates="job", cascade="all, delete-orphan", order_by="Interview.scheduled_at"
    )


class JobEvent(Base):
    """Append-only timeline. Never mutate a row here - history must stay truthful."""

    __tablename__ = 'job_events'
    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey('jobs.id'), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)

    job = relationship("Job", back_populates="events")


class Document(Base):
    """Every resume / cover letter ever generated, versioned per job."""

    __tablename__ = 'documents'
    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey('jobs.id'), nullable=True, index=True)
    kind = Column(String, nullable=False)          # resume | cover_letter
    version = Column(Integer, default=1)
    file_path = Column(String, nullable=False)
    content_snapshot = Column(Text, nullable=True) # JSON of the tailored content
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    is_current = Column(Boolean, default=True)

    job = relationship("Job", back_populates="documents")


class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey('jobs.id'), nullable=True, index=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=True)           # recruiter, hiring manager, referral
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    last_contacted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    job = relationship("Job", back_populates="contacts")


class Interview(Base):
    __tablename__ = 'interviews'
    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey('jobs.id'), nullable=False, index=True)
    round_name = Column(String, nullable=False)    # screen, tech 1, system design, HR
    scheduled_at = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    interviewer = Column(String, nullable=True)
    mode = Column(String, nullable=True)           # phone, video, onsite
    outcome = Column(String, default="SCHEDULED")
    prep_notes = Column(Text, nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    job = relationship("Job", back_populates="interviews")


class SavedSearch(Base):
    """Search definitions live in the DB so they can be edited from the UI."""

    __tablename__ = 'saved_searches'
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    location = Column(String, nullable=True)
    work_mode = Column(String, nullable=True)
    results_wanted = Column(Integer, default=50)
    hours_old = Column(Integer, default=168)
    is_enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_found = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class LLMUsage(Base):
    __tablename__ = 'llm_usage'
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey('runs.id'), nullable=True)
    job_id = Column(String, ForeignKey('jobs.id'), nullable=True)
    purpose = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=utcnow)


Index("ix_jobs_status_score", Job.status, Job.match_score)
