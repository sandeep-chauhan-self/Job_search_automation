"""Shared test fixtures.

Keeps every test off the real data/jobs.db so runs are repeatable and never
pollute the user's actual pipeline data.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base


@pytest.fixture
def temp_db(tmp_path):
    """An isolated SQLite session backed by a per-test file."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
