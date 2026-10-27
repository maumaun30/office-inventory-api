from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers import assignments, categories, items, locations


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Office Inventory API",
    description="Track office equipment and supplies: items, categories, locations, and who has what.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(categories.router)
app.include_router(locations.router)
app.include_router(items.router)
app.include_router(assignments.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
