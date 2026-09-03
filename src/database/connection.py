import logging
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from src.database.models import Base

# DB Path points to data/jobs.db in project root unless overridden.
DB_DIR = os.environ.get("JOBSEARCH_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
)
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.environ.get("JOBSEARCH_DB_PATH") or os.path.join(DB_DIR, "jobs.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def _sqlite_type(column) -> str:
    name = column.type.__class__.__name__.upper()
    return {
        "STRING": "VARCHAR",
        "TEXT": "TEXT",
        "INTEGER": "INTEGER",
        "FLOAT": "FLOAT",
        "DATETIME": "DATETIME",
        "BOOLEAN": "BOOLEAN",
    }.get(name, "VARCHAR")


def ensure_schema() -> None:
    """Create tables, then add any columns added to models since the DB was made.

    SQLAlchemy's create_all only creates missing *tables* - it will not alter an
    existing one, so a schema change would otherwise raise OperationalError on
    every query against an older database.
    """
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {_sqlite_type(column)}'
                conn.execute(text(ddl))
                logging.info("Schema upgrade: added %s.%s", table.name, column.name)


ensure_schema()

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
