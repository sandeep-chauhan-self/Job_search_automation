import pytest
from fastapi.testclient import TestClient
from src.dashboard.app import app
from src.database.models import Job, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def test_db():
    import tempfile
    import os
    db_fd, db_path = tempfile.mkstemp()
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except:
        pass

@pytest.fixture
def client(test_db):
    from src.database.connection import get_db_context
    def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db_context] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_list_jobs(client, test_db):
    test_db.add(Job(title="Software Engineer", company="Google", platform="google_jobs", job_url="http", dedup_hash="1", status="DISCOVERED"))
    test_db.commit()
    
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["jobs"][0]["company"] == "Google"

import pytest
from fastapi.testclient import TestClient
from src.dashboard.app import app
from src.database.models import Job, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def test_db():
    import tempfile
    import os
    db_fd, db_path = tempfile.mkstemp()
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except:
        pass

@pytest.fixture
def client(test_db):
    from src.database.connection import get_db_context
    def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db_context] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_list_jobs(client, test_db):
    test_db.add(Job(title="Software Engineer", company="Google", platform="google_jobs", job_url="http", dedup_hash="1", status="DISCOVERED"))
    test_db.commit()
    
    response = client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["jobs"][0]["company"] == "Google"

def test_analytics(client, test_db):
    test_db.add(Job(title="Software Engineer", company="Google", platform="google_jobs", job_url="http", dedup_hash="1", status="APPLIED", match_score=90))
    test_db.commit()
    
    response = client.get("/api/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_applied"] == 1
    assert data["avg_match_score"] == 90


def _seed(db, **overrides):
    fields = dict(
        title="Backend Engineer",
        company="Acme",
        platform="linkedin",
        job_url="https://example.com/job",
        dedup_hash="seed-1",
        status="SCORED",
        match_score=75,
    )
    fields.update(overrides)
    job = Job(**fields)
    db.add(job)
    db.commit()
    return job


def test_job_detail_parses_reasons_and_gaps(client, test_db):
    job = _seed(test_db, match_reasons='["Strong Python"]', match_gaps='["No Kubernetes"]')

    data = client.get(f"/api/jobs/{job.id}").json()
    assert data["match_reasons"] == ["Strong Python"]
    assert data["match_gaps"] == ["No Kubernetes"]
    assert data["has_resume"] is False


def test_job_detail_survives_malformed_json(client, test_db):
    job = _seed(test_db, match_reasons="not json at all")
    assert client.get(f"/api/jobs/{job.id}").json()["match_reasons"] == []


def test_status_update_rejects_unknown_value(client, test_db):
    job = _seed(test_db)
    assert client.patch(f"/api/jobs/{job.id}/status", json={"status": "PWNED"}).status_code == 422
    assert client.patch(f"/api/jobs/{job.id}/status", json={"status": "APPROVED"}).status_code == 200
    test_db.refresh(job)
    assert job.status == "APPROVED"


def test_bulk_status_update(client, test_db):
    first = _seed(test_db, dedup_hash="bulk-1")
    second = _seed(test_db, dedup_hash="bulk-2", company="Globex")

    res = client.post("/api/jobs/bulk-status", json={"job_ids": [first.id, second.id], "status": "APPROVED"})
    assert res.status_code == 200
    assert res.json()["updated"] == 2


def test_filters_and_search(client, test_db):
    _seed(test_db, dedup_hash="f-1", company="Acme", match_score=90, status="SCORED")
    _seed(test_db, dedup_hash="f-2", company="Globex", match_score=30, status="SKIPPED")

    assert client.get("/api/jobs?min_score=80").json()["total"] == 1
    assert client.get("/api/jobs?search=globex").json()["total"] == 1
    assert client.get("/api/jobs?status=SCORED,SKIPPED").json()["total"] == 2


def test_missing_document_returns_404(client, test_db):
    job = _seed(test_db)
    assert client.get(f"/api/jobs/{job.id}/document/resume").status_code == 404


def test_document_path_outside_output_is_blocked(client, test_db):
    job = _seed(test_db, resume_path="C:/Windows/System32/drivers/etc/hosts")
    assert client.get(f"/api/jobs/{job.id}/document/resume").status_code == 404


def test_run_endpoints(client):
    snapshot = client.get("/api/runs/current").json()
    assert snapshot["active"] is False
    assert snapshot["status"] == "IDLE"

    # Nothing running, so cancel must not pretend it worked.
    assert client.post("/api/runs/cancel").status_code == 409
    assert client.post("/api/runs/apply", json={"job_ids": []}).status_code == 422


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_funnel_is_cumulative_and_monotonic(client, test_db):
    # An applied job must still count as discovered/scored/approved upstream.
    _seed(test_db, dedup_hash="fun-1", status="APPLIED", match_score=90,
          applied_at=__import__("datetime").datetime(2026, 1, 1))
    _seed(test_db, dedup_hash="fun-2", status="DISCOVERED", match_score=None)

    funnel = {row["stage"]: row["count"] for row in client.get("/api/analytics/summary").json()["funnel"]}

    assert funnel["DISCOVERED"] == 2
    assert funnel["SCORED"] == 1
    assert funnel["APPLIED"] == 1

    counts = [funnel[s] for s in ["DISCOVERED", "SCORED", "SHORTLISTED", "RESUME_READY", "APPLIED", "INTERVIEW", "OFFER"]]
    assert counts == sorted(counts, reverse=True), f"funnel must never increase downstream: {counts}"


def test_applied_counted_without_timestamp(client, test_db):
    # Hand-imported rows carry the status but no applied_at; they must still count.
    _seed(test_db, dedup_hash="noTs-1", status="APPLIED", applied_at=None)

    data = client.get("/api/analytics/summary").json()
    assert data["total_applied"] == 1


def test_funnel_monotonic_when_shortlisted_without_score(client, test_db):
    # Shortlisting by hand skips scoring entirely, which must not make an
    # upstream stage smaller than a downstream one.
    _seed(test_db, dedup_hash="ns-1", status="APPLIED", match_score=None, applied_at=None)
    _seed(test_db, dedup_hash="ns-2", status="SHORTLISTED", match_score=None)

    funnel = {row["stage"]: row["count"] for row in client.get("/api/analytics/summary").json()["funnel"]}
    counts = [funnel[s] for s in ["DISCOVERED", "SCORED", "SHORTLISTED", "RESUME_READY", "APPLIED", "INTERVIEW", "OFFER"]]
    assert counts == sorted(counts, reverse=True), f"funnel must never increase downstream: {counts}"
    assert funnel["SCORED"] == 2
