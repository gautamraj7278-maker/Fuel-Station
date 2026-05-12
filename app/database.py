import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


BASE_DIR = Path(__file__).resolve().parent.parent


# -------------------------------------------------
# SQLITE URL NORMALIZER
# -------------------------------------------------
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


# -------------------------------------------------
# SAFE DATABASE URL DISPLAY
# -------------------------------------------------
def _mask_database_url(url: str) -> str:
    try:
        parsed = urlsplit(url)

        if parsed.password:
            username = parsed.username or ""
            hostname = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""

            netloc = f"{username}:****@{hostname}{port}"
            return urlunsplit(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )

        return url
    except Exception:
        return "DATABASE_URL configured"


# -------------------------------------------------
# DATABASE URL
# -------------------------------------------------
SQLALCHEMY_DATABASE_URL = settings.database_url

if not SQLALCHEMY_DATABASE_URL:
    raise Exception("DATABASE_URL is not set in settings/environment")

SQLALCHEMY_DATABASE_URL = _resolve_sqlite_url(SQLALCHEMY_DATABASE_URL)

print("ACTIVE DATABASE URL:")
print(_mask_database_url(SQLALCHEMY_DATABASE_URL))


# -------------------------------------------------
# ENGINE
# -------------------------------------------------
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    use_null_pool = os.getenv("DB_USE_NULL_POOL", "false").lower() in {"1", "true", "yes"}

    if use_null_pool:
        # Useful when an external pooler (for example Supabase pooler) is already in front.
        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=300,
            poolclass=NullPool,
        )
    else:
        pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))

        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_use_lifo=True,
        )


# -------------------------------------------------
# SESSION
# -------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# -------------------------------------------------
# BASE MODEL
# -------------------------------------------------
Base = declarative_base()


# -------------------------------------------------
# DB DEPENDENCY
# -------------------------------------------------
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
