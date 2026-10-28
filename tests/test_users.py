def make_item(client, **overrides):
    payload = {"name": "Laptop", "quantity": 3}
    payload.update(overrides)
    return client.post("/items", json=payload).json()


def test_list_and_get_users(client, laravel):
    assert [u["name"] for u in client.get("/users").json()] == ["Ana", "Ben", "Cy"]
    assert client.get("/users/2").json()["email"] == "ben@example.com"
    assert client.get("/users/99").status_code == 404
    proxied = [r for r in laravel.requests if r.url.path != "/api/user"]
    assert proxied[0].headers["Authorization"] == "Bearer test-token"


def test_assign_unknown_user_rejected(client):
    item = make_item(client)
    resp = client.post("/assignments", json={"item_id": item["id"], "user_id": 99})
    assert resp.status_code == 422
    assert client.get(f"/items/{item['id']}").json()["assigned_quantity"] == 0


def test_laravel_down_returns_503(client, laravel):
    item = make_item(client)
    laravel.down = True
    assert client.post("/assignments", json={"item_id": item["id"], "user_id": 1}).status_code == 503
    assert client.get("/users").status_code == 503


def test_local_checks_skip_laravel_call(client, laravel):
    item = make_item(client, status="retired")
    assert client.post("/assignments", json={"item_id": item["id"], "user_id": 1}).status_code == 409
    assert [r.url.path for r in laravel.requests] == ["/api/user"]  # auth only, then cached


def test_user_assignments_survive_laravel_outage(client, laravel):
    item = make_item(client)
    a = client.post("/assignments", json={"item_id": item["id"], "user_id": 1}).json()
    client.post("/assignments", json={"item_id": item["id"], "user_id": 2})
    client.post(f"/assignments/{a['id']}/return")

    laravel.down = True
    held = client.get("/users/1/assignments").json()
    assert [x["assignee_name"] for x in held] == ["Ana"]
    assert client.get("/users/1/assignments", params={"active": True}).json() == []
    assert [x["user_id"] for x in client.get("/assignments", params={"user_id": 2}).json()] == [2]
