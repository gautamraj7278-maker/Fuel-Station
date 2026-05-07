import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent

# Normalize relative sqlite URLs so restarts always hit the same DB file.
def _resolve_sqlite_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url
    if url.startswith("sqlite:////"):
        return url

    path_and_query = url[len("sqlite:///"):]
    if not path_and_query or path_and_query.startswith(":memory:"):
        return url

    path_part, sep, query = path_and_query.partition("?")
    path = Path(path_part)
    if not path.is_absolute():
        path = BASE_DIR / path

    normalized = f"sqlite:///{path.as_posix()}"
    if sep:
        normalized = f"{normalized}?{query}"
    return normalized

# Database URL - can be configured via environment variable
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    settings.database_url,
)
SQLALCHEMY_DATABASE_URL = _resolve_sqlite_url(SQLALCHEMY_DATABASE_URL)

# Create engine
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)

# Create session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
