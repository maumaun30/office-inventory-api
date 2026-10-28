import threading
import time

import pytest
from fastapi.testclient import TestClient

import app.routers.assignments as assignments_router
from app.main import app
from tests.conftest import ADMIN, STAFF, TEST_DATABASE_URL

ADMIN_ID = 1  # admin-token resolves to FAKE_USERS[1]


def make_item(client, **overrides):
    payload = {"name": "Laptop", "quantity": 3}
    payload.update(overrides)
    resp = client.post("/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def movements(client, item_id):
    resp = client.get(f"/items/{item_id}/movements")
    assert resp.status_code == 200, resp.text
    return [(m["kind"], m["delta"], m["quantity_after"], m["reason"]) for m in resp.json()]


def test_stock_changes_are_logged(client):
    item = make_item(client, quantity=3)
    client.post(f"/items/{item['id']}/adjust", json={"delta": -1, "reason": "broken"})
    client.post(f"/items/{item['id']}/adjust", json={"delta": 0})  # no-op, not logged
    client.patch(f"/items/{item['id']}", json={"quantity": 10})
    client.patch(f"/items/{item['id']}", json={"name": "Renamed"})  # no quantity change

    assert movements(client, item["id"]) == [
        ("initial", 3, 3, None),
        ("adjust", -1, 2, "broken"),
        ("edit", 8, 10, None),
    ]
    users = {m["user_id"] for m in client.get(f"/items/{item['id']}/movements").json()}
    assert users == {ADMIN_ID}


def test_zero_quantity_item_has_no_initial_movement(client):
    item = make_item(client, quantity=0)
    assert movements(client, item["id"]) == []


def test_rejected_adjust_not_logged(client):
    item = make_item(client, quantity=1)
    assert client.post(f"/items/{item['id']}/adjust", json={"delta": -5}).status_code == 409
    assert movements(client, item["id"]) == [("initial", 1, 1, None)]


def test_movements_admin_only(client):
    item = make_item(client)
    assert client.get(f"/items/{item['id']}/movements", headers=STAFF).status_code == 403
    assert client.get("/items/999/movements").status_code == 404


def test_delete_item_removes_movements(client):
    item = make_item(client)
    assert client.delete(f"/items/{item['id']}").status_code == 204
    assert client.get(f"/items/{item['id']}/movements").status_code == 404


def test_assignment_records_actors(client):
    item = make_item(client)
    a = client.post("/assignments", json={"item_id": item["id"], "user_id": 2}).json()
    assert a["assigned_by_user_id"] == ADMIN_ID
    assert a["returned_by_user_id"] is None

    returned = client.post(f"/assignments/{a['id']}/return").json()
    assert returned["returned_by_user_id"] == ADMIN_ID


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="SQLite ignores row locks; needs Postgres")
def test_concurrent_assignments_cannot_over_assign(client, monkeypatch):
    item = make_item(client, quantity=1)

    # Widen the check-then-insert window so unsynchronized requests reliably overlap.
    original_check = assignments_router._check_assignable

    def slow_check(*args):
        original_check(*args)
        time.sleep(0.1)

    monkeypatch.setattr(assignments_router, "_check_assignable", slow_check)
    n = 8
    barrier = threading.Barrier(n)
    codes: list[int] = []

    def worker():
        # Own client per thread so requests really run in parallel.
        with TestClient(app, headers=ADMIN) as c:
            barrier.wait()
            codes.append(
                c.post("/assignments", json={"item_id": item["id"], "user_id": 2}).status_code
            )

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(codes) == [201] + [409] * (n - 1)
    assert client.get(f"/items/{item['id']}").json()["assigned_quantity"] == 1
