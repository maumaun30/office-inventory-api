import importlib

from fastapi.testclient import TestClient

import app.main


def _client(monkeypatch, **env):
    for key in ("CORS_ORIGINS", "CORS_ORIGIN_REGEX"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(importlib.reload(app.main).app)


def _preflight(client, origin):
    return client.options(
        "/items",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_cors_disabled_by_default(monkeypatch):
    client = _client(monkeypatch)
    assert "access-control-allow-origin" not in _preflight(client, "https://ui.example").headers


def test_cors_allows_listed_and_pattern_origins(monkeypatch):
    client = _client(
        monkeypatch,
        CORS_ORIGINS="https://ui.example, http://localhost:5173",
        CORS_ORIGIN_REGEX=r"https://office-inventory-ui-.*\.vercel\.app",
    )
    for origin in ("https://ui.example", "https://office-inventory-ui-abc.vercel.app"):
        resp = _preflight(client, origin)
        assert resp.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers

    resp = client.get("/health", headers={"Origin": "https://ui.example"})
    assert "X-Total-Count" in resp.headers["access-control-expose-headers"]


def teardown_module():
    importlib.reload(app.main)
