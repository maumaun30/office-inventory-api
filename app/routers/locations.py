from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import DB, commit_or_409, get_or_404
from app.models import Location
from app.schemas import LocationCreate, LocationRead, LocationUpdate

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[LocationRead])
def list_locations(db: DB):
    return db.scalars(select(Location).order_by(Location.name)).all()


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, db: DB):
    location = Location(**payload.model_dump())
    db.add(location)
    commit_or_409(db)
    return location


@router.get("/{location_id}", response_model=LocationRead)
def get_location(location_id: int, db: DB):
    return get_or_404(db, Location, location_id)


@router.patch("/{location_id}", response_model=LocationRead)
def update_location(location_id: int, payload: LocationUpdate, db: DB):
    location = get_or_404(db, Location, location_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field, value)
    commit_or_409(db)
    return location


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: int, db: DB):
    location = get_or_404(db, Location, location_id)
    for item in location.items:
        item.location_id = None
    db.delete(location)
    db.commit()
