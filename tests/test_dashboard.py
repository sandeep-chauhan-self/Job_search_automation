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
