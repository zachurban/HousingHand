"""FastAPI dependency injection utilities for HousingHand."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from src.database.connection import get_session_factory


# ---------------------------------------------------------------------------
# Database session dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session that is closed after the request.

    This is the canonical FastAPI dependency for obtaining a database
    session.  It mirrors ``src.database.connection.get_db`` but is placed
    here so that the API layer can be tested independently (by overriding
    this single dependency) without touching the database module.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Annotated shorthand so endpoints can write ``db: DbSession`` instead of
# repeating ``Depends(get_db)`` everywhere.
DbSession = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Settings dependency
# ---------------------------------------------------------------------------

SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationParams(BaseModel):
    """Common pagination query parameters.

    Used as a FastAPI dependency so that every list endpoint shares the
    same ``limit`` / ``offset`` contract.
    """

    limit: int
    offset: int

    model_config = {"frozen": True}


def get_pagination(
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of records to return"),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of records to skip"),
    ] = 0,
) -> PaginationParams:
    """Parse and validate pagination query parameters."""
    return PaginationParams(limit=limit, offset=offset)


PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]
