from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.users_client import UsersClient, UsersServiceError, get_users_client

DB = Annotated[Session, Depends(get_db)]


def users_client() -> UsersClient:
    try:
        return get_users_client()
    except UsersServiceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


Users = Annotated[UsersClient, Depends(users_client)]


def optional_users_client() -> UsersClient | None:
    """Like `users_client`, but None instead of 503 when not configured."""
    try:
        return get_users_client()
    except UsersServiceError:
        return None


M = TypeVar("M", bound=Base)


def get_or_404(db: Session, model: type[M], obj_id: int) -> M:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {obj_id} not found")
    return obj


def get_for_update(db: Session, model: type[M], obj_id: int) -> M:
    """Row-lock `obj_id` for the rest of the transaction, then load it.

    Lock and load are separate statements on purpose: under READ COMMITTED a
    single SELECT ... FOR UPDATE that waited on another transaction still
    evaluates subqueries (like Item.assigned_quantity) against its old
    snapshot. A fresh SELECT after the lock sees the other commit.
    SQLite ignores FOR UPDATE; use Postgres for real concurrency.
    """
    pk = model.__mapper__.primary_key[0]
    if db.scalar(select(pk).where(pk == obj_id).with_for_update()) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {obj_id} not found")
    return db.get(model, obj_id, populate_existing=True)


def commit_or_409(db: Session) -> None:
    """Commit, turning unique-constraint violations into 409 Conflict."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Resource conflicts with an existing record"
        ) from exc
