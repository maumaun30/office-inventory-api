from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import ItemStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Categories ---

class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class CategoryRead(CategoryBase, ORMModel):
    id: int


# --- Locations ---

class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    building: str | None = None
    floor: str | None = None
    room: str | None = None


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    building: str | None = None
    floor: str | None = None
    room: str | None = None


class LocationRead(LocationBase, ORMModel):
    id: int


# --- Items ---

class ItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=100)
    description: str | None = None
    quantity: int = Field(default=1, ge=0)
    reorder_level: int = Field(default=0, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    status: ItemStatus = ItemStatus.active
    category_id: int | None = None
    location_id: int | None = None


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=100)
    description: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    reorder_level: int | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    status: ItemStatus | None = None
    category_id: int | None = None
    location_id: int | None = None


class ItemRead(ItemBase, ORMModel):
    id: int
    assigned_quantity: int
    available_quantity: int
    created_at: datetime
    updated_at: datetime
    category: CategoryRead | None = None
    location: LocationRead | None = None


class StockAdjust(BaseModel):
    delta: int = Field(description="Positive to add stock, negative to remove.")
    reason: str | None = None


# --- Assignments ---

class AssignmentCreate(BaseModel):
    item_id: int
    assignee_name: str = Field(min_length=1, max_length=100)
    assignee_email: EmailStr | None = None
    quantity: int = Field(default=1, ge=1)
    notes: str | None = None


class AssignmentRead(ORMModel):
    id: int
    item_id: int
    assignee_name: str
    assignee_email: str | None
    quantity: int
    notes: str | None
    assigned_at: datetime
    returned_at: datetime | None


# --- Stats ---

class InventorySummary(BaseModel):
    total_items: int
    total_units: int
    assigned_units: int
    total_value: float
    low_stock_items: int
    by_status: dict[str, int]
