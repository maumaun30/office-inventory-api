from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import admin_only
from app.deps import DB, Users
from app.models import Assignment
from app.schemas import AssignmentRead
from app.users_client import ExternalUser, UserNotFound

router = APIRouter(prefix="/users", tags=["users"], dependencies=[admin_only])


@router.get("", response_model=list[ExternalUser])
def list_users(
    users: Users,
    request: Request,
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int | None, Query(ge=1, le=100)] = None,
):
    """Proxy to the Laravel users API.

    Pagination is reported in headers so the body stays a plain list:
    `X-Page`, `X-Per-Page`, `X-Total-Count`, `X-Last-Page`, and `Link`
    (`rel="next"` / `rel="prev"`).
    """
    result = users.list_users(page=page, per_page=per_page)
    response.headers["X-Page"] = str(result.page)
    response.headers["X-Per-Page"] = str(result.per_page)
    if result.total is not None:
        response.headers["X-Total-Count"] = str(result.total)
    links = []
    if result.last_page is not None:
        response.headers["X-Last-Page"] = str(result.last_page)
        if result.page < result.last_page:
            links.append(f'<{request.url.include_query_params(page=result.page + 1)}>; rel="next"')
    if result.page > 1:
        links.append(f'<{request.url.include_query_params(page=result.page - 1)}>; rel="prev"')
    if links:
        response.headers["Link"] = ", ".join(links)
    return result.users


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
    return assignments_for_user(db, user_id, active)


def assignments_for_user(db: Session, user_id: int, active: bool | None) -> list[Assignment]:
    stmt = select(Assignment).where(Assignment.user_id == user_id)
    if active is True:
        stmt = stmt.where(Assignment.returned_at.is_(None))
    elif active is False:
        stmt = stmt.where(Assignment.returned_at.is_not(None))
    return list(db.scalars(stmt.order_by(Assignment.assigned_at.desc())))
