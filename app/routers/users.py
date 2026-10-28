from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import DB, Users
from app.models import Assignment
from app.schemas import AssignmentRead
from app.users_client import ExternalUser, UserNotFound

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[ExternalUser])
def list_users(users: Users, page: Annotated[int, Query(ge=1)] = 1):
    """Proxy to the Laravel users API (paginated)."""
    return users.list_users(page=page)


@router.get("/{user_id}", response_model=ExternalUser)
def get_user(user_id: int, users: Users):
    try:
        return users.get_user(user_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {user_id} not found") from None


@router.get("/{user_id}/assignments", response_model=list[AssignmentRead])
def user_assignments(
    user_id: int,
    db: DB,
    active: Annotated[bool | None, Query(description="true = not yet returned")] = None,
):
    """Assignments held by a user. Reads local records only; no Laravel call."""
    stmt = select(Assignment).where(Assignment.user_id == user_id)
    if active is True:
        stmt = stmt.where(Assignment.returned_at.is_(None))
    elif active is False:
        stmt = stmt.where(Assignment.returned_at.is_not(None))
    return db.scalars(stmt.order_by(Assignment.assigned_at.desc())).all()
