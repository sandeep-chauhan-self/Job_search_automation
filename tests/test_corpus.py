import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import constants as C
from src import corpus
from src.dashboard.app import app
from src.database.models import Base, Document, Interview, Job, JobEvent


@pytest.fixture
def test_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(test_db):
    from src.database.connection import get_db_context

    # Must be a generator function, not iter([...]) - that is consumed after one
    # request and every later call would get an exhausted iterator.
    def override():
        yield test_db

    app.dependency_overrides[get_db_context] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_job(db, **overrides):
    fields = dict(
        title="Backend Engineer",
        company="Acme",
        platform="linkedin",
        job_url="https://example.com/j",
        dedup_hash="corpus-1",
        status=C.STATUS_SCORED,
        match_score=80,
    )
    fields.update(overrides)
    job = Job(**fields)
    db.add(job)
    db.commit()
    return job


# -- status history ----------------------------------------------------------


def test_status_change_records_event(test_db):
    job = make_job(test_db)
    corpus.change_status(test_db, job, C.STATUS_APPLIED, reason="submitted")

    events = test_db.query(JobEvent).filter(JobEvent.job_id == job.id).all()
    assert len(events) == 1
    assert events[0].from_status == C.STATUS_SCORED
    assert events[0].to_status == C.STATUS_APPLIED
    assert events[0].detail == "submitted"


def test_applying_sets_timestamp_once(test_db):
    job = make_job(test_db)
    corpus.change_status(test_db, job, C.STATUS_APPLIED)
    first = job.applied_at
    assert first is not None

    corpus.change_status(test_db, job, C.STATUS_INTERVIEW)
    assert job.applied_at == first, "advancing past APPLIED must not rewrite the original apply date"


def test_closing_a_job_clears_follow_up(test_db):
    from datetime import datetime

    job = make_job(test_db, follow_up_at=datetime(2026, 1, 1))
    corpus.change_status(test_db, job, C.STATUS_REJECTED)
    assert job.follow_up_at is None


# -- document versioning -----------------------------------------------------


def test_documents_are_versioned(test_db):
    job = make_job(test_db)

    corpus.register_document(test_db, job, C.DOCUMENT_RESUME, "output/resumes/v1.pdf")
    corpus.register_document(test_db, job, C.DOCUMENT_RESUME, "output/resumes/v2.pdf")

    docs = test_db.query(Document).filter(Document.job_id == job.id).order_by(Document.version).all()
    assert [d.version for d in docs] == [1, 2]
    assert [d.is_current for d in docs] == [False, True]
    assert job.resume_path == "output/resumes/v2.pdf"


# -- attention buckets -------------------------------------------------------


def test_needs_attention_surfaces_due_follow_ups(test_db):
    from datetime import timedelta

    overdue = corpus.utcnow() - timedelta(days=2)
    make_job(test_db, dedup_hash="a", follow_up_at=overdue)
    make_job(test_db, dedup_hash="b", follow_up_at=corpus.utcnow() + timedelta(days=5))

    buckets = corpus.needs_attention(test_db)
    assert len(buckets["due_follow_ups"]) == 1


def test_needs_attention_flags_stale_applications(test_db):
    from datetime import timedelta

    make_job(
        test_db,
        dedup_hash="stale",
        status=C.STATUS_APPLIED,
        applied_at=corpus.utcnow() - timedelta(days=30),
    )
    buckets = corpus.needs_attention(test_db, stale_after_days=10)
    assert len(buckets["stale_applications"]) == 1


# -- API ---------------------------------------------------------------------


def test_today_dashboard(client, test_db):
    from datetime import timedelta

    make_job(test_db, dedup_hash="t1", follow_up_at=corpus.utcnow() - timedelta(days=1))
    data = client.get("/api/dashboard/today").json()
    assert len(data["due_follow_ups"]) == 1


def test_interview_lifecycle(client, test_db):
    job = make_job(test_db)

    created = client.post(
        f"/api/jobs/{job.id}/interviews",
        json={"round_name": "Tech Screen", "scheduled_at": "2026-10-01T10:00:00", "mode": "video"},
    )
    assert created.status_code == 200
    interview_id = created.json()["id"]

    test_db.refresh(job)
    assert job.status == C.STATUS_INTERVIEW, "scheduling an interview should advance the job"

    assert client.patch(f"/api/interviews/{interview_id}", json={"outcome": "PASSED"}).status_code == 200
    assert test_db.query(Interview).filter(Interview.id == interview_id).first().outcome == "PASSED"

    assert client.patch(f"/api/interviews/{interview_id}", json={"outcome": "BOGUS"}).status_code == 422


def test_contact_crud(client, test_db):
    job = make_job(test_db)

    assert client.post(f"/api/jobs/{job.id}/contacts", json={"role": "recruiter"}).status_code == 422

    created = client.post(
        f"/api/jobs/{job.id}/contacts", json={"name": "Dana", "role": "recruiter"}
    )
    assert created.status_code == 200
    assert client.delete(f"/api/contacts/{created.json()['id']}").status_code == 200


def test_job_patch_updates_tracking_fields(client, test_db):
    job = make_job(test_db)

    res = client.patch(
        f"/api/jobs/{job.id}",
        json={"is_favorite": True, "priority": 3, "tags": ["dream", "remote"]},
    )
    assert res.status_code == 200
    assert res.json()["is_favorite"] is True
    assert res.json()["priority"] == 3
    assert res.json()["tags"] == ["dream", "remote"]


def test_priority_is_clamped(client, test_db):
    job = make_job(test_db)
    assert client.patch(f"/api/jobs/{job.id}", json={"priority": 99}).json()["priority"] == 3


def test_archived_jobs_hidden_by_default(client, test_db):
    job = make_job(test_db)
    client.patch(f"/api/jobs/{job.id}", json={"archived": True})

    assert client.get("/api/jobs").json()["total"] == 0
    assert client.get("/api/jobs?include_archived=true").json()["total"] == 1


def test_job_detail_includes_timeline(client, test_db):
    job = make_job(test_db)
    client.patch(f"/api/jobs/{job.id}/status", json={"status": "APPLIED"})
    client.post(f"/api/jobs/{job.id}/notes", json={"note": "Referred by Dana"})

    detail = client.get(f"/api/jobs/{job.id}").json()
    kinds = {e["type"] for e in detail["events"]}
    assert C.EVENT_STATUS_CHANGED in kinds
    assert C.EVENT_NOTE in kinds


def test_csv_export(client, test_db):
    make_job(test_db, company="Globex")
    res = client.get("/api/export/jobs.csv")
    assert res.status_code == 200
    assert "Globex" in res.text
    assert "company,title,location" in res.text


def test_assistant_requires_key(client, monkeypatch):
    # Without a configured key the endpoint must refuse rather than call out.
    from src.settings import settings
    monkeypatch.setattr(settings, "llm_api_key", "")
    res = client.post("/api/assistant/ask", json={"question": "What are my skills?"})
    assert res.status_code in (409, 502)


def test_profile_status_detects_placeholder(client):
    data = client.get("/api/profile/status").json()
    assert "score" in data
    assert "missing" in data
