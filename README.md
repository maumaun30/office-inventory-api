# Office Inventory API

FastAPI + SQLAlchemy service for tracking office equipment and supplies.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/fastapi dev app/main.py     # http://127.0.0.1:8000/docs
```

Database defaults to SQLite (`./inventory.db`, created on startup). Override with `DATABASE_URL`.

## Resources

| Endpoint | Purpose |
|---|---|
| `/categories` | CRUD for item categories |
| `/locations` | CRUD for rooms / floors / buildings |
| `/items` | CRUD; filters `q`, `category_id`, `location_id`, `status`, `low_stock`, `skip`, `limit` |
| `POST /items/{id}/adjust` | Add/remove stock (`{"delta": -2}`) |
| `GET /items/summary` | Totals, value, assigned units, low-stock count |
| `/assignments` | Check items out to people; filters `item_id`, `assignee`, `active` |
| `POST /assignments/{id}/return` | Check an item back in |

Rules: an item can't be assigned beyond its available quantity or while `in_repair`/`retired`; its quantity can't drop below what's assigned; items with open assignments can't be deleted. Low stock = available ≤ `reorder_level`.

## Tests

```bash
.venv/bin/pytest
```
