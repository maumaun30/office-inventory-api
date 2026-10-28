from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth import admin_only
from app.deps import DB, Users, get_or_404
from app.models import Assignment, Item, ItemStatus
from app.schemas import AssignmentCreate, AssignmentRead
from app.users_client import UserNotFound

router = APIRouter(prefix="/assignments", tags=["assignments"], dependencies=[admin_only])


@router.get("", response_model=list[AssignmentRead])
def list_assignments(
    db: DB,
    item_id: int | None = None,
    user_id: int | None = None,
    assignee: Annotated[str | None, Query(description="Match assignee name or email")] = None,
    active: Annotated[bool | None, Query(description="true = not yet returned")] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    stmt = select(Assignment)
    if item_id is not None:
        stmt = stmt.where(Assignment.item_id == item_id)
    if user_id is not None:
        stmt = stmt.where(Assignment.user_id == user_id)
    if assignee:
        pattern = f"%{assignee}%"
        stmt = stmt.where(
            Assignment.assignee_name.ilike(pattern) | Assignment.assignee_email.ilike(pattern)
        )
    if active is True:
        stmt = stmt.where(Assignment.returned_at.is_(None))
    elif active is False:
        stmt = stmt.where(Assignment.returned_at.is_not(None))
    stmt = stmt.order_by(Assignment.assigned_at.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreate, db: DB, users: Users):
    item = get_or_404(db, Item, payload.item_id)
    if item.status != ItemStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Item is {item.status.value}, cannot assign")
    if payload.quantity > item.available_quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only {item.available_quantity} unit(s) available",
        )
    try:
        user = users.get_user(payload.user_id)
    except UserNotFound:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"User {payload.user_id} not found"
        ) from None
    assignment = Assignment(
        **payload.model_dump(), assignee_name=user.name, assignee_email=user.email
    )
    db.add(assignment)
    db.commit()
    return assignment


@router.get("/{assignment_id}", response_model=AssignmentRead)
def get_assignment(assignment_id: int, db: DB):
    return get_or_404(db, Assignment, assignment_id)


@router.post("/{assignment_id}/return", response_model=AssignmentRead)
def return_assignment(assignment_id: int, db: DB):
    assignment = get_or_404(db, Assignment, assignment_id)
    if assignment.returned_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Assignment already returned")
    assignment.returned_at = datetime.now(timezone.utc)
    db.commit()
    return assignment
