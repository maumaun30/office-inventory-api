import os

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
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

# Browser clients (the web UI) on other origins. Bearer tokens, no cookies.
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
cors_origin_regex = os.getenv("CORS_ORIGIN_REGEX") or None
if cors_origins or cors_origin_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[
            "X-Page",
            "X-Per-Page",
            "X-Total-Count",
            "X-Last-Page",
            "Link",
            "Content-Disposition",
        ],
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
