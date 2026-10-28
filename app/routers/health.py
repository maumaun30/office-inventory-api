import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.deps import DB, optional_users_client
from app.users_client import UsersClient, UsersServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["meta"])


@router.get("")
def health():
    """Liveness: the process is up. No dependencies checked."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DB, users: Annotated[UsersClient | None, Depends(optional_users_client)]):
    """Readiness: database and Laravel users API are reachable; 503 if not.

    Public, so failures are reported as plain "error"; details go to the log.
    """
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError:
        logger.exception("Readiness: database check failed")
        checks["database"] = "error"
    try:
        if users is None:
            raise UsersServiceError("USERS_API_URL is not configured")
        users.ping()
        checks["users_api"] = "ok"
    except UsersServiceError:
        logger.exception("Readiness: users API check failed")
        checks["users_api"] = "error"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "error", "checks": checks},
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
