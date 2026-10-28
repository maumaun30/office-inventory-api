from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import Authenticated, CurrentUser
from app.deps import DB
from app.routers.users import assignments_for_user
from app.schemas import AssignmentRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=CurrentUser)
def me(user: Authenticated):
    return user


@router.get("/assignments", response_model=list[AssignmentRead])
def my_assignments(
    user: Authenticated,
    db: DB,
    active: Annotated[bool | None, Query(description="true = not yet returned")] = None,
):
    return assignments_for_user(db, user.id, active)
