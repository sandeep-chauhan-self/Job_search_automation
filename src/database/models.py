import uuid
import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base

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
    status = Column(String, default="DISCOVERED")
    match_score = Column(Integer, nullable=True)
    match_reasons = Column(Text, nullable=True) # JSON string
    match_gaps = Column(Text, nullable=True) # JSON string
    resume_path = Column(String, nullable=True)
    cover_letter_path = Column(String, nullable=True)
    salary_info = Column(String, nullable=True)
    work_mode = Column(String, nullable=True)
    discovered_at = Column(DateTime, default=utcnow)
    scored_at = Column(DateTime, nullable=True)
    resume_generated_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    applied_method = Column(String, nullable=True)
    run_id = Column(String, ForeignKey('runs.id'), nullable=True)
    notes = Column(Text, nullable=True)

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
