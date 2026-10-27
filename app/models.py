import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ItemStatus(str, enum.Enum):
    active = "active"
    in_repair = "in_repair"
    retired = "retired"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["Item"]] = relationship(back_populates="category")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    building: Mapped[str | None] = mapped_column(String(100))
    floor: Mapped[str | None] = mapped_column(String(20))
    room: Mapped[str | None] = mapped_column(String(50))

    items: Mapped[list["Item"]] = relationship(back_populates="location")


class Assignment(Base):
    """An item (or some quantity of it) checked out to a person."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    assignee_name: Mapped[str] = mapped_column(String(100))
    assignee_email: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped["Item"] = relationship(back_populates="assignments")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    sku: Mapped[str | None] = mapped_column(String(64), unique=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float | None]
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.active)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    category: Mapped[Category | None] = relationship(back_populates="items")
    location: Mapped[Location | None] = relationship(back_populates="items")
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    # Units currently checked out (open assignments).
    assigned_quantity: Mapped[int] = column_property(
        select(func.coalesce(func.sum(Assignment.quantity), 0))
        .where(Assignment.item_id == id, Assignment.returned_at.is_(None))
        .correlate_except(Assignment)
        .scalar_subquery()
    )

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.assigned_quantity
