from contextlib import contextmanager # <--- 1. Import this
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session

from data_utils.settings import DatabaseSettings

# 1. Global storage
_engine = None
_SessionLocal = None

def get_db_url(original_dsn: str) -> str:
    url = make_url(original_dsn)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)

def init_db(settings: DatabaseSettings):
    global _engine, _SessionLocal
    if _engine:
        return

    _engine = create_engine(
        get_db_url(settings.pg_dsn),
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=10,
    )

    _SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine
    )

def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db(settings) first.")
    return _SessionLocal()

# 2. Add the decorator here
@contextmanager 
def get_db_context(settings: DatabaseSettings) -> Generator[Session, None, None]:
    """
    Context manager for python 'with' statements.
    
    Usage:
        with get_db_context(settings) as session:
            session.execute(...)
    """
    # Ensure init if not already done
    init_db(settings)

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()