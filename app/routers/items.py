from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import admin_only, authenticated
from app.deps import DB, commit_or_409, get_or_404
from app.models import Category, Item, ItemStatus, Location
from app.schemas import InventorySummary, ItemCreate, ItemRead, ItemUpdate, StockAdjust

router = APIRouter(prefix="/items", tags=["items"], dependencies=[authenticated])


def _validate_refs(db: Session, data: dict) -> None:
    if data.get("category_id") is not None:
        get_or_404(db, Category, data["category_id"])
    if data.get("location_id") is not None:
        get_or_404(db, Location, data["location_id"])


def _ensure_covers_assigned(item: Item, new_quantity: int) -> None:
    if new_quantity < item.assigned_quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Quantity {new_quantity} is below the {item.assigned_quantity} units currently assigned",
        )


def _save(db: Session, item: Item) -> Item:
    commit_or_409(db)
    db.refresh(item)  # reload computed assigned_quantity
    return item


@router.get("", response_model=list[ItemRead])
def list_items(
    db: DB,
    q: Annotated[str | None, Query(description="Search name, SKU, or serial number")] = None,
    category_id: int | None = None,
    location_id: int | None = None,
    status_: Annotated[ItemStatus | None, Query(alias="status")] = None,
    low_stock: Annotated[bool, Query(description="Only items at or below reorder level")] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    stmt = select(Item).options(selectinload(Item.category), selectinload(Item.location))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(Item.name.ilike(pattern), Item.sku.ilike(pattern), Item.serial_number.ilike(pattern))
        )
    if category_id is not None:
        stmt = stmt.where(Item.category_id == category_id)
    if location_id is not None:
        stmt = stmt.where(Item.location_id == location_id)
    if status_ is not None:
        stmt = stmt.where(Item.status == status_)
    if low_stock:
        stmt = stmt.where(Item.quantity - Item.assigned_quantity <= Item.reorder_level)
    stmt = stmt.order_by(Item.name).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/summary", response_model=InventorySummary)
def inventory_summary(db: DB):
    total_items, total_units, total_value = db.execute(
        select(
            func.count(Item.id),
            func.coalesce(func.sum(Item.quantity), 0),
            func.coalesce(func.sum(Item.quantity * func.coalesce(Item.unit_cost, 0)), 0),
        )
    ).one()
    assigned_units = db.scalar(select(func.coalesce(func.sum(Item.assigned_quantity), 0)))
    low_stock_items = db.scalar(
        select(func.count(Item.id)).where(
            Item.quantity - Item.assigned_quantity <= Item.reorder_level
        )
    )
    by_status = {s.value: 0 for s in ItemStatus}
    for item_status, count in db.execute(select(Item.status, func.count()).group_by(Item.status)):
        by_status[item_status.value] = count
    return InventorySummary(
        total_items=total_items,
        total_units=total_units,
        assigned_units=assigned_units,
        total_value=round(float(total_value), 2),
        low_stock_items=low_stock_items,
        by_status=by_status,
    )


@router.post(
    "", response_model=ItemRead, status_code=status.HTTP_201_CREATED, dependencies=[admin_only]
)
def create_item(payload: ItemCreate, db: DB):
    data = payload.model_dump()
    _validate_refs(db, data)
    item = Item(**data)
    db.add(item)
    return _save(db, item)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, db: DB):
    return get_or_404(db, Item, item_id)


@router.patch("/{item_id}", response_model=ItemRead, dependencies=[admin_only])
def update_item(item_id: int, payload: ItemUpdate, db: DB):
    item = get_or_404(db, Item, item_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_refs(db, data)
    if data.get("quantity") is not None:
        _ensure_covers_assigned(item, data["quantity"])
    for field, value in data.items():
        setattr(item, field, value)
    return _save(db, item)


@router.post("/{item_id}/adjust", response_model=ItemRead, dependencies=[admin_only])
def adjust_stock(item_id: int, payload: StockAdjust, db: DB):
    item = get_or_404(db, Item, item_id)
    new_quantity = item.quantity + payload.delta
    if new_quantity < 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stock cannot go below zero")
    _ensure_covers_assigned(item, new_quantity)
    item.quantity = new_quantity
    return _save(db, item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_only])
def delete_item(item_id: int, db: DB):
    item = get_or_404(db, Item, item_id)
    if item.assigned_quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Item has open assignments; return them before deleting"
        )
    db.delete(item)
    db.commit()
