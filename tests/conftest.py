import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import token_cache
from app.database import Base, get_db
from app.deps import optional_users_client, users_client
from app.main import app
from app.users_client import UsersClient

# Run against Postgres with e.g.
#   TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/inventory_test pytest
# The database is wiped by each test. Defaults to in-memory SQLite.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def make_engine():
    if TEST_DATABASE_URL:
        return create_engine(TEST_DATABASE_URL)
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


FAKE_USERS = {
    1: {"id": 1, "name": "Ana", "email": "ana@example.com"},
    2: {"id": 2, "name": "Ben", "email": "ben@example.com"},
    3: {"id": 3, "name": "Cy", "email": None},
}

# Caller tokens -> user payload from Laravel's GET /api/user.
TOKENS = {
    "admin-token": {**FAKE_USERS[1], "role": "admin"},
    "staff-token": {**FAKE_USERS[2], "role": "staff"},
}
ADMIN = {"Authorization": "Bearer admin-token"}
STAFF = {"Authorization": "Bearer staff-token"}


class FakeLaravel:
    """httpx transport that mimics Laravel API Resource responses."""

    def __init__(self):
        self.down = False
        self.paginated = True  # False: /api/users returns no meta block
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/user":
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            user = TOKENS.get(token)
            if user is None:
                return httpx.Response(401, json={"message": "Unauthenticated."})
            return httpx.Response(200, json=user)
        if request.url.path == "/up":
            return httpx.Response(200, text="OK")
        if request.url.path == "/api/users":
            # Mimic Laravel's LengthAwarePaginator response.
            page = int(request.url.params.get("page", 1))
            per_page = int(request.url.params.get("per_page", 50))
            users = list(FAKE_USERS.values())
            last_page = max(1, -(-len(users) // per_page))
            chunk = users[(page - 1) * per_page : page * per_page]
            meta = {
                "current_page": page,
                "per_page": per_page,
                "total": len(users),
                "last_page": last_page,
            }
            if not self.paginated:
                return httpx.Response(200, json={"data": users})
            return httpx.Response(200, json={"data": chunk, "links": {}, "meta": meta})
        if m := re.fullmatch(r"/api/users/(\d+)", request.url.path):
            user = FAKE_USERS.get(int(m[1]))
            if user is None:
                return httpx.Response(404, json={"message": "Not found."})
            return httpx.Response(200, json={"data": user})
        return httpx.Response(404)


@pytest.fixture
def laravel():
    return FakeLaravel()


@pytest.fixture
def engine():
    engine = make_engine()
    Base.metadata.drop_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(laravel, engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    fake_users = UsersClient(
        "http://laravel.test", token="test-token", transport=httpx.MockTransport(laravel)
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[users_client] = lambda: fake_users
    app.dependency_overrides[optional_users_client] = lambda: fake_users
    token_cache.clear()
    with TestClient(app, headers=ADMIN) as c:
        yield c
    app.dependency_overrides.clear()
    token_cache.clear()
