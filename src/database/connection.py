import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.database.models import Base

# DB Path points to data/jobs.db in project root
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "jobs.db")

engine = create_engine(f"sqlite:///{DB_PATH}")

# Create tables if they don't exist
Base.metadata.create_all(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    """Returns a new SQLAlchemy session connected to data/jobs.db"""
    db = SessionLocal()
    return db

def get_db_context():
    """Generator for use with context managers or FastAPI Depends"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
