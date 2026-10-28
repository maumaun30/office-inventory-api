import pytest

import app.auth as auth
from app.auth import AuthSettings, CurrentUser, TokenCache, is_admin
from tests.conftest import STAFF, TOKENS

NO_AUTH = {"Authorization": ""}


def auth_calls(laravel):
    return [r for r in laravel.requests if r.url.path == "/api/user"]


def test_health_is_public(client):
    assert client.get("/health", headers=NO_AUTH).status_code == 200


def test_missing_token_401(client):
    resp = client.get("/items", headers=NO_AUTH)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_token_401(client):
    resp = client.get("/items", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_failed_lookups_not_cached(client, laravel):
    for _ in range(2):
        client.get("/items", headers={"Authorization": "Bearer nope"})
    assert len(auth_calls(laravel)) == 2


def test_staff_can_read_but_not_write(client):
    item = client.post("/items", json={"name": "Laptop", "quantity": 2}).json()

    assert client.get("/items", headers=STAFF).status_code == 200
    assert client.get(f"/items/{item['id']}", headers=STAFF).status_code == 200
    assert client.get("/items/summary", headers=STAFF).status_code == 200
    assert client.get("/categories", headers=STAFF).status_code == 200

    assert client.post("/items", json={"name": "X"}, headers=STAFF).status_code == 403
    assert (
        client.patch(f"/items/{item['id']}", json={"name": "Y"}, headers=STAFF).status_code == 403
    )
    assert (
        client.post(f"/items/{item['id']}/adjust", json={"delta": 1}, headers=STAFF).status_code
        == 403
    )
    assert client.delete(f"/items/{item['id']}", headers=STAFF).status_code == 403
    assert client.post("/categories", json={"name": "C"}, headers=STAFF).status_code == 403
    assert client.post("/locations", json={"name": "L"}, headers=STAFF).status_code == 403


@pytest.mark.parametrize("path", ["/assignments", "/users", "/users/1", "/users/1/assignments"])
def test_admin_only_reads(client, path):
    assert client.get(path, headers=STAFF).status_code == 403


def test_me(client):
    assert client.get("/me").json()["is_admin"] is True
    me = client.get("/me", headers=STAFF).json()
    assert me == {"id": 2, "name": "Ben", "email": "ben@example.com", "is_admin": False}


def test_my_assignments_only_shows_own(client):
    item = client.post("/items", json={"name": "Laptop", "quantity": 3}).json()
    client.post("/assignments", json={"item_id": item["id"], "user_id": 1})
    mine = client.post("/assignments", json={"item_id": item["id"], "user_id": 2}).json()

    held = client.get("/me/assignments", headers=STAFF).json()
    assert [a["id"] for a in held] == [mine["id"]]


def test_token_lookup_cached(client, laravel):
    for _ in range(3):
        client.get("/items", headers=STAFF)
    assert len(auth_calls(laravel)) == 1


def test_laravel_down_on_first_auth_503(client, laravel):
    laravel.down = True
    assert client.get("/items", headers=STAFF).status_code == 503


def test_admin_field_configurable(client, laravel, monkeypatch):
    monkeypatch.setitem(TOKENS, "flag-token", {"id": 3, "name": "Cy", "is_admin": True})
    monkeypatch.setattr(auth, "get_auth_settings", lambda: AuthSettings(admin_field="is_admin"))
    resp = client.post(
        "/categories", json={"name": "C"}, headers={"Authorization": "Bearer flag-token"}
    )
    assert resp.status_code == 201


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("admin", True),
        ("staff", False),
        (True, True),
        (False, False),
        (["staff", "admin"], True),
        ([{"name": "admin", "guard_name": "web"}], True),
        ([{"name": "staff"}], False),
        (None, False),
        (1, False),
    ],
)
def test_is_admin_shapes(value, expected):
    assert is_admin(value, frozenset({"admin"})) is expected


def test_token_cache_expiry(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    cache = TokenCache()
    user = CurrentUser(id=1, name="Ana")
    cache.set("t", user, ttl=60)
    assert cache.get("t") == user
    now[0] += 61
    assert cache.get("t") is None
