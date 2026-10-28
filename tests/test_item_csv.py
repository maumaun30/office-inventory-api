import csv
import io

from tests.conftest import STAFF


def upload(client, text, **params):
    return client.post(
        "/items/import",
        params=params,
        files={"file": ("items.csv", text.encode(), "text/csv")},
    )


def parse(resp):
    return list(csv.DictReader(io.StringIO(resp.text)))


def items_by_name(client):
    return {i["name"]: i for i in client.get("/items").json()}


def test_export(client):
    cat = client.post("/categories", json={"name": "IT"}).json()
    client.post(
        "/items", json={"name": "Laptop", "sku": "LT-1", "quantity": 2, "category_id": cat["id"]}
    )
    client.post("/items", json={"name": "Chair", "quantity": 0})

    resp = client.get("/items/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = parse(resp)
    assert [r["name"] for r in rows] == ["Laptop", "Chair"]
    assert rows[0]["category"] == "IT" and rows[0]["sku"] == "LT-1"
    assert rows[1]["category"] == "" and rows[1]["sku"] == ""


def test_export_allowed_for_staff_import_is_not(client):
    assert client.get("/items/export", headers=STAFF).status_code == 200
    resp = client.post(
        "/items/import", headers=STAFF, files={"file": ("x.csv", b"name\nX\n", "text/csv")}
    )
    assert resp.status_code == 403


def test_export_neutralizes_formulas_and_round_trips(client):
    client.post("/items", json={"name": '=HYPERLINK("http://evil")', "description": "-1+2"})
    exported = client.get("/items/export")
    row = parse(exported)[0]
    assert row["name"] == '\'=HYPERLINK("http://evil")'
    assert row["description"] == "'-1+2"

    # Re-importing the export matches by id and changes nothing
    resp = upload(client, exported.text)
    assert resp.status_code == 200, resp.text
    assert resp.json()["unchanged"] == 1
    assert client.get("/items").json()[0]["name"] == '=HYPERLINK("http://evil")'


def test_import_creates_items_and_lookups(client):
    text = (
        "name,sku,quantity,unit_cost,status,category,location\n"
        "Monitor,MON-1,4,199.99,active,Electronics,HQ-2F\n"
        "Desk,,1,,,Furniture,HQ-2F\n"
    )
    resp = upload(client, text)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "dry_run": False,
        "created": 2,
        "updated": 0,
        "unchanged": 0,
        "created_categories": ["Electronics", "Furniture"],
        "created_locations": ["HQ-2F"],
    }
    items = items_by_name(client)
    assert items["Monitor"]["quantity"] == 4
    assert items["Monitor"]["category"]["name"] == "Electronics"
    assert items["Desk"]["location"]["name"] == "HQ-2F"
    movements = client.get(f"/items/{items['Monitor']['id']}/movements").json()
    assert [(m["kind"], m["delta"], m["reason"]) for m in movements] == [
        ("initial", 4, "csv import")
    ]


def test_import_updates_by_sku_and_leaves_blanks(client):
    client.post("/categories", json={"name": "IT"})
    item = client.post(
        "/items", json={"name": "Laptop", "sku": "LT-1", "quantity": 2, "description": "keep me"}
    ).json()

    resp = upload(client, "name,sku,quantity,description,category\nLaptop Pro,LT-1,5,,IT\n")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert resp.json()["created_categories"] == []

    updated = client.get(f"/items/{item['id']}").json()
    assert updated["name"] == "Laptop Pro"
    assert updated["quantity"] == 5
    assert updated["description"] == "keep me"
    assert updated["category"]["name"] == "IT"
    kinds = [(m["kind"], m["delta"]) for m in client.get(f"/items/{item['id']}/movements").json()]
    assert kinds == [("initial", 2), ("edit", 3)]


def test_import_is_all_or_nothing(client):
    client.post("/items", json={"name": "Existing", "serial_number": "SN-1"})
    text = (
        "name,sku,serial_number,quantity,status\n"
        "Good,G-1,,1,active\n"
        ",G-2,,1,active\n"  # missing name
        "Bad qty,G-3,,-4,active\n"
        "Bad status,G-4,,1,lost\n"
        "Dup,G-1,,1,active\n"  # repeats line 2's sku
        "Clash,G-5,SN-1,1,active\n"  # serial taken by another item
    )
    resp = upload(client, text)
    assert resp.status_code == 422
    errors = {e["row"]: e["errors"] for e in resp.json()["detail"]["errors"]}
    assert set(errors) == {3, 4, 5, 6, 7}
    assert any("name" in m for m in errors[3])
    assert any("quantity" in m for m in errors[4])
    assert any("status" in m for m in errors[5])
    assert any("repeats line 2" in m for m in errors[6])
    assert any("already used by item" in m for m in errors[7])
    assert list(items_by_name(client)) == ["Existing"]


def test_import_unknown_id_and_conflicting_sku(client):
    a = client.post("/items", json={"name": "A", "sku": "A-1"}).json()
    client.post("/items", json={"name": "B", "sku": "B-1"})
    resp = upload(client, f"id,name,sku\n999,X,\n{a['id']},A,B-1\n")
    assert resp.status_code == 422
    errors = {e["row"]: e["errors"] for e in resp.json()["detail"]["errors"]}
    assert "does not exist" in errors[2][0]
    assert "belongs to item" in errors[3][0]


def test_import_cannot_drop_below_assigned(client):
    item = client.post("/items", json={"name": "Laptop", "sku": "LT-1", "quantity": 2}).json()
    client.post("/assignments", json={"item_id": item["id"], "user_id": 2, "quantity": 2})
    resp = upload(client, "name,sku,quantity\nLaptop,LT-1,1\n")
    assert resp.status_code == 409
    assert client.get(f"/items/{item['id']}").json()["quantity"] == 2


def test_dry_run_saves_nothing(client):
    resp = upload(client, "name,category\nMonitor,Electronics\n", dry_run=True)
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert resp.json()["created"] == 1
    assert client.get("/items").json() == []
    assert client.get("/categories").json() == []


def test_import_rejects_bad_files(client):
    assert upload(client, "sku,quantity\nX,1\n").status_code == 422  # no name column
    assert upload(client, "").status_code == 422
    bad_utf8 = client.post(
        "/items/import", files={"file": ("x.csv", b"name\n\xff\xfe\n", "text/csv")}
    )
    assert bad_utf8.status_code == 422
    big = "name\n" + "x\n" * 5001
    assert upload(client, big).status_code == 413


def test_import_accepts_excel_bom_and_spaced_headers(client):
    resp = client.post(
        "/items/import",
        files={"file": ("x.csv", "﻿ name , quantity \nMonitor,3\n".encode(), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    assert items_by_name(client)["Monitor"]["quantity"] == 3
