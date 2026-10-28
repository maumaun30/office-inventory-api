from fastapi import APIRouter, status
from sqlalchemy import select

from app.auth import admin_only, authenticated
from app.deps import DB, commit_or_409, get_or_404
from app.models import Category
from app.schemas import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[authenticated])


@router.get("", response_model=list[CategoryRead])
def list_categories(db: DB):
    return db.scalars(select(Category).order_by(Category.name)).all()


@router.post(
    "", response_model=CategoryRead, status_code=status.HTTP_201_CREATED, dependencies=[admin_only]
)
def create_category(payload: CategoryCreate, db: DB):
    category = Category(**payload.model_dump())
    db.add(category)
    commit_or_409(db)
    return category


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(category_id: int, db: DB):
    return get_or_404(db, Category, category_id)


@router.patch("/{category_id}", response_model=CategoryRead, dependencies=[admin_only])
def update_category(category_id: int, payload: CategoryUpdate, db: DB):
    category = get_or_404(db, Category, category_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    commit_or_409(db)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_only])
def delete_category(category_id: int, db: DB):
    category = get_or_404(db, Category, category_id)
    for item in category.items:
        item.category_id = None
    db.delete(category)
    db.commit()
