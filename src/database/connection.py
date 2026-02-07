"""Database connection and session management."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""

    pass


def get_engine(database_url: str | None = None):
    """Create and return a SQLAlchemy engine."""
    settings = get_settings()
    url = database_url or settings.database_url
    return create_engine(
        url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    """Create and return a session factory."""
    engine = get_engine(database_url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependency injection."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
