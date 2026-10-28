import re

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.deps import users_client
from app.main import app
from app.users_client import UsersClient

FAKE_USERS = {
    1: {"id": 1, "name": "Ana", "email": "ana@example.com"},
    2: {"id": 2, "name": "Ben", "email": "ben@example.com"},
    3: {"id": 3, "name": "Cy", "email": None},
}


class FakeLaravel:
    """httpx transport that mimics Laravel API Resource responses."""

    def __init__(self):
        self.down = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/users":
            return httpx.Response(200, json={"data": list(FAKE_USERS.values()), "meta": {}})
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
def client(laravel):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
