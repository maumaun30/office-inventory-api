from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.routers import (
    assignments,
    categories,
    health,
    item_csv,
    items,
    locations,
    me,
    users,
)
from app.users_client import UsersServiceError

# Schema is managed by Alembic: run `alembic upgrade head` before starting.
app = FastAPI(
    title="Office Inventory API",
    description=(
        "Track office equipment and supplies: items, categories, locations, and who has what."
    ),
    version="1.0.0",
)

app.include_router(categories.router)
app.include_router(locations.router)
app.include_router(item_csv.router)  # before items: /items/export vs /items/{item_id}
app.include_router(items.router)
app.include_router(assignments.router)
app.include_router(users.router)
app.include_router(me.router)
app.include_router(health.router)


@app.exception_handler(UsersServiceError)
def users_service_error(request: Request, exc: UsersServiceError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )
