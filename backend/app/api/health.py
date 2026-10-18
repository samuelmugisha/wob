from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, str | None]:
    try:
        pgvector = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ok" if pgvector else "degraded", "database": "ok", "pgvector": pgvector}
