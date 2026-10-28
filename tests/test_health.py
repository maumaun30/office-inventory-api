from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.deps import optional_users_client
from app.main import app

NO_AUTH = {"Authorization": ""}


def test_liveness_public(client):
    assert client.get("/health", headers=NO_AUTH).json() == {"status": "ok"}


def test_head_probes(client, laravel):
    assert client.head("/health", headers=NO_AUTH).status_code == 200
    assert client.head("/health/ready", headers=NO_AUTH).status_code == 200
    laravel.down = True
    assert client.head("/health/ready", headers=NO_AUTH).status_code == 503


def test_ready_ok(client, laravel):
    resp = client.get("/health/ready", headers=NO_AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": "ok", "users_api": "ok"}}
    assert [r.url.path for r in laravel.requests] == ["/up"]


def test_ready_laravel_down(client, laravel):
    laravel.down = True
    resp = client.get("/health/ready", headers=NO_AUTH)
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "ok", "users_api": "error"}
    assert "refused" not in resp.text  # no internal details on a public endpoint


def test_ready_users_api_not_configured(client):
    app.dependency_overrides[optional_users_client] = lambda: None
    resp = client.get("/health/ready", headers=NO_AUTH)
    assert resp.status_code == 503
    assert resp.json()["checks"]["users_api"] == "error"


def test_ready_database_down(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("db host unreachable"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    resp = client.get("/health/ready", headers=NO_AUTH)
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "error", "users_api": "ok"}
    assert "unreachable" not in resp.text
