# Office Inventory API

FastAPI + SQLAlchemy service for tracking office equipment and supplies.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/fastapi dev app/main.py     # http://127.0.0.1:8000/docs
```

Database defaults to SQLite (`./inventory.db`, created on startup). Override with `DATABASE_URL`.

### Users (Laravel)

Users live in a separate Laravel API. Configure via env (see `.env.example`):

| Variable | Purpose |
|---|---|
| `USERS_API_URL` | Laravel base URL, e.g. `https://hr.example.com` |
| `USERS_API_TOKEN` | Sanctum token, sent as `Authorization: Bearer ...` |
| `USERS_API_TIMEOUT` | Seconds, default `5` |

Expected Laravel endpoints (standard API Resource shape):

- `GET /api/users?page=N` returns `{"data": [{"id", "name", "email"}, ...]}`
- `GET /api/users/{id}` returns `{"data": {"id", "name", "email"}}`, or 404

Creating an assignment looks up the user and snapshots name/email onto the record, so history and `/users/{id}/assignments` keep working if Laravel is down or the user changes. Unknown user returns 422; Laravel unreachable or unconfigured returns 503.

## Resources

| Endpoint | Purpose |
|---|---|
| `/categories` | CRUD for item categories |
| `/locations` | CRUD for rooms / floors / buildings |
| `/items` | CRUD; filters `q`, `category_id`, `location_id`, `status`, `low_stock`, `skip`, `limit` |
| `POST /items/{id}/adjust` | Add/remove stock (`{"delta": -2}`) |
| `GET /items/summary` | Totals, value, assigned units, low-stock count |
| `/assignments` | Check items out to users (`{"item_id": 1, "user_id": 12}`); filters `item_id`, `user_id`, `assignee`, `active` |
| `POST /assignments/{id}/return` | Check an item back in |
| `GET /users`, `GET /users/{id}` | Proxied from Laravel |
| `GET /users/{id}/assignments` | Items a user holds (local data); filter `active` |

Rules: an item can't be assigned beyond its available quantity or while `in_repair`/`retired`; its quantity can't drop below what's assigned; items with open assignments can't be deleted. Low stock = available ≤ `reorder_level`.

## Tests

```bash
.venv/bin/pytest
```
