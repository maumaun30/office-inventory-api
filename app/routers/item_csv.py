"""CSV export and import for items.

Mounted before the main items router so `/items/export` and `/items/import`
aren't captured by `/items/{item_id}`.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import Admin, admin_only, authenticated
from app.deps import DB, commit_or_409, get_for_update
from app.models import Category, Item, Location, MovementKind
from app.routers.items import _ensure_covers_assigned, _record_movement
from app.schemas import ImportResult, ImportRowError, ItemCreate, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"], dependencies=[authenticated])

EXPORT_COLUMNS = [
    "id",
    "name",
    "sku",
    "serial_number",
    "description",
    "quantity",
    "reorder_level",
    "unit_cost",
    "status",
    "category",
    "location",
    "assigned_quantity",
    "available_quantity",
]
# Columns import reads; anything else (assigned/available, unknown) is ignored.
ITEM_FIELDS = [
    "name",
    "sku",
    "serial_number",
    "description",
    "quantity",
    "reorder_level",
    "unit_cost",
    "status",
]
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 5000

# Spreadsheet apps treat cells starting with these as formulas (CSV injection).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _unescape_cell(value: str) -> str:
    if value.startswith("'") and value[1:].startswith(FORMULA_PREFIXES):
        return value[1:]
    return value


@router.get("/export", response_class=Response)
def export_items(db: DB):
    """All items as CSV. Text cells that look like formulas are prefixed with `'`."""
    items = db.scalars(
        select(Item)
        .options(selectinload(Item.category), selectinload(Item.location))
        .order_by(Item.id)
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for item in items:
        row = {
            **{f: getattr(item, f) for f in ITEM_FIELDS},
            "id": item.id,
            "status": item.status.value,
            "category": item.category.name if item.category else None,
            "location": item.location.name if item.location else None,
            "assigned_quantity": item.assigned_quantity,
            "available_quantity": item.available_quantity,
        }
        writer.writerow(["" if row[c] is None else _safe_cell(row[c]) for c in EXPORT_COLUMNS])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="items.csv"'},
    )


@dataclass
class _Plan:
    """Validated import, ready to apply."""

    creates: list[tuple[dict, str | None, str | None]] = field(default_factory=list)
    updates: list[tuple[int, dict, str | None, str | None]] = field(default_factory=list)
    unchanged: int = 0
    errors: list[ImportRowError] = field(default_factory=list)


def _error_messages(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]


def _plan_import(db: Session, rows: list[dict[str, str]]) -> _Plan:
    plan = _Plan()
    by_id = {i.id: i for i in db.scalars(select(Item))}
    by_sku = {i.sku: i for i in by_id.values() if i.sku}
    by_serial = {i.serial_number: i for i in by_id.values() if i.serial_number}
    seen_targets: dict[int, int] = {}
    seen_sku: dict[str, int] = {}
    seen_serial: dict[str, int] = {}

    for line, raw in enumerate(rows, start=2):
        values = {k: _unescape_cell(v.strip()) for k, v in raw.items() if k and v and v.strip()}
        errors: list[str] = []

        target: Item | None = None
        if "id" in values:
            try:
                target = by_id.get(int(values["id"]))
            except ValueError:
                errors.append("id: must be an integer")
            if target is None and not errors:
                errors.append(f"id: item {values['id']} does not exist")
        sku = values.get("sku")
        if sku and sku in by_sku:
            if target is not None and by_sku[sku] is not target:
                errors.append(f"sku: {sku!r} belongs to item {by_sku[sku].id}, not {target.id}")
            target = target or by_sku[sku]

        for key, seen, label in (
            (sku, seen_sku, "sku"),
            (values.get("serial_number"), seen_serial, "serial_number"),
        ):
            if key:
                if key in seen:
                    errors.append(f"{label}: {key!r} repeats line {seen[key]}")
                seen[key] = line
        serial = values.get("serial_number")
        if serial and serial in by_serial and by_serial[serial] is not target:
            errors.append(f"serial_number: {serial!r} already used by item {by_serial[serial].id}")
        if target is not None:
            if target.id in seen_targets:
                errors.append(f"matches item {target.id}, same as line {seen_targets[target.id]}")
            seen_targets[target.id] = line

        for col in ("category", "location"):
            if len(values.get(col, "")) > 100:
                errors.append(f"{col}: name must be at most 100 characters")

        data = {k: values[k] for k in ITEM_FIELDS if k in values}
        try:
            if target is None:
                data = ItemCreate(**data).model_dump(exclude={"category_id", "location_id"})
            else:
                data = ItemUpdate(**data).model_dump(exclude_unset=True)
        except ValidationError as exc:
            errors.extend(_error_messages(exc))

        if errors:
            plan.errors.append(ImportRowError(row=line, errors=errors))
            continue

        category, location = values.get("category"), values.get("location")
        if target is None:
            plan.creates.append((data, category, location))
            continue
        changed = any(getattr(target, k) != v for k, v in data.items())
        changed |= category is not None and (
            target.category is None or target.category.name != category
        )
        changed |= location is not None and (
            target.location is None or target.location.name != location
        )
        if changed:
            plan.updates.append((target.id, data, category, location))
        else:
            plan.unchanged += 1
    return plan


def _resolve(
    db: Session, model: type[Category] | type[Location], names: set[str]
) -> tuple[dict, list[str]]:
    existing = {o.name: o for o in db.scalars(select(model).where(model.name.in_(names)))}
    created = sorted(names - existing.keys())
    for name in created:
        existing[name] = model(name=name)
        db.add(existing[name])
    return existing, created


@router.post("/import", response_model=ImportResult, dependencies=[admin_only])
async def import_items(
    db: DB,
    admin: Admin,
    file: Annotated[UploadFile, File(description="CSV with a header row; see GET /items/export")],
    dry_run: Annotated[bool, Query(description="Validate and report without saving")] = False,
):
    """Create or update items from CSV. All-or-nothing: any invalid row rejects the file.

    Rows match an existing item by `id`, then by `sku`; otherwise a new item is
    created. Blank cells leave fields unchanged on update. Missing categories and
    locations are created by name. Quantity changes are logged as stock movements.
    """
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File exceeds 2 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File must be UTF-8") from None

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "name" not in [f.strip() for f in reader.fieldnames]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Header row must include 'name'")
    reader.fieldnames = [f.strip() for f in reader.fieldnames]
    try:
        rows = [row for _, row in zip(range(MAX_IMPORT_ROWS + 1), reader, strict=False)]
    except csv.Error as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Malformed CSV: {exc}"
        ) from None
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {MAX_IMPORT_ROWS} rows"
        )

    plan = _plan_import(db, rows)
    if plan.errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "No rows imported", "errors": [e.model_dump() for e in plan.errors]},
        )

    pending = plan.creates + [u[1:] for u in plan.updates]
    categories, new_categories = _resolve(db, Category, {c for _, c, _ in pending if c})
    locations, new_locations = _resolve(db, Location, {loc for _, _, loc in pending if loc})

    for data, category, location in plan.creates:
        item = Item(**data, category=categories.get(category), location=locations.get(location))
        if item.quantity:
            _record_movement(item, MovementKind.initial, item.quantity, admin.id, "csv import")
        db.add(item)

    for item_id, data, category, location in plan.updates:
        item = get_for_update(db, Item, item_id)
        new_quantity = data.get("quantity")
        if new_quantity is not None:
            try:
                _ensure_covers_assigned(item, new_quantity)
            except HTTPException as exc:
                db.rollback()
                raise HTTPException(exc.status_code, f"Item {item_id}: {exc.detail}") from None
        delta = new_quantity - item.quantity if new_quantity is not None else 0
        for key, value in data.items():
            setattr(item, key, value)
        if category is not None:
            item.category = categories[category]
        if location is not None:
            item.location = locations[location]
        if delta:
            _record_movement(item, MovementKind.edit, delta, admin.id, "csv import")

    result = ImportResult(
        dry_run=dry_run,
        created=len(plan.creates),
        updated=len(plan.updates),
        unchanged=plan.unchanged,
        created_categories=new_categories,
        created_locations=new_locations,
    )
    if dry_run:
        db.rollback()
    else:
        commit_or_409(db)
    return result
