def make_item(client, **overrides):
    payload = {"name": "Laptop", "quantity": 5, "reorder_level": 1, "unit_cost": 1000}
    payload.update(overrides)
    resp = client.post("/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_category_crud_and_conflict(client):
    resp = client.post("/categories", json={"name": "Electronics"})
    assert resp.status_code == 201
    cat_id = resp.json()["id"]

    assert client.post("/categories", json={"name": "Electronics"}).status_code == 409
    assert client.patch(f"/categories/{cat_id}", json={"description": "Gadgets"}).json()[
        "description"
    ] == "Gadgets"
    assert client.delete(f"/categories/{cat_id}").status_code == 204
    assert client.get(f"/categories/{cat_id}").status_code == 404


def test_item_with_refs(client):
    cat = client.post("/categories", json={"name": "Furniture"}).json()
    loc = client.post("/locations", json={"name": "HQ-2F", "building": "HQ", "floor": "2"}).json()
    item = make_item(client, name="Desk", category_id=cat["id"], location_id=loc["id"])
    assert item["category"]["name"] == "Furniture"
    assert item["location"]["name"] == "HQ-2F"

    assert client.post("/items", json={"name": "Chair", "category_id": 999}).status_code == 404


def test_item_filters(client):
    make_item(client, name="Monitor", sku="MON-1")
    make_item(client, name="Stapler", quantity=1, reorder_level=2, status="active")
    make_item(client, name="Old Printer", status="retired")

    names = lambda r: [i["name"] for i in r.json()]
    assert names(client.get("/items", params={"q": "mon"})) == ["Monitor"]
    assert names(client.get("/items", params={"status": "retired"})) == ["Old Printer"]
    assert names(client.get("/items", params={"low_stock": True})) == ["Stapler"]


def test_assignment_lifecycle(client):
    item = make_item(client, quantity=2)

    a1 = client.post(
        "/assignments",
        json={"item_id": item["id"], "assignee_name": "Ana", "assignee_email": "ana@example.com"},
    )
    assert a1.status_code == 201
    client.post("/assignments", json={"item_id": item["id"], "assignee_name": "Ben"})

    fetched = client.get(f"/items/{item['id']}").json()
    assert fetched["assigned_quantity"] == 2
    assert fetched["available_quantity"] == 0

    # Nothing left
    over = client.post("/assignments", json={"item_id": item["id"], "assignee_name": "Cy"})
    assert over.status_code == 409

    # Can't shrink stock below what's assigned, or delete
    assert client.patch(f"/items/{item['id']}", json={"quantity": 1}).status_code == 409
    assert client.delete(f"/items/{item['id']}").status_code == 409

    # Return one
    ret = client.post(f"/assignments/{a1.json()['id']}/return")
    assert ret.status_code == 200 and ret.json()["returned_at"]
    assert client.post(f"/assignments/{a1.json()['id']}/return").status_code == 409
    assert client.get(f"/items/{item['id']}").json()["available_quantity"] == 1

    active = client.get("/assignments", params={"active": True}).json()
    assert [a["assignee_name"] for a in active] == ["Ben"]


def test_cannot_assign_inactive_item(client):
    item = make_item(client, status="in_repair")
    resp = client.post("/assignments", json={"item_id": item["id"], "assignee_name": "Ana"})
    assert resp.status_code == 409


def test_stock_adjust(client):
    item = make_item(client, quantity=3)
    assert client.post(f"/items/{item['id']}/adjust", json={"delta": 4}).json()["quantity"] == 7
    assert client.post(f"/items/{item['id']}/adjust", json={"delta": -10}).status_code == 409


def test_summary(client):
    make_item(client, quantity=2, unit_cost=100)
    stapler = make_item(client, name="Stapler", quantity=1, reorder_level=1, unit_cost=5.5)
    client.post("/assignments", json={"item_id": stapler["id"], "assignee_name": "Ana"})

    s = client.get("/items/summary").json()
    assert s["total_items"] == 2
    assert s["total_units"] == 3
    assert s["assigned_units"] == 1
    assert s["total_value"] == 205.5
    assert s["low_stock_items"] == 1
    assert s["by_status"]["active"] == 2
