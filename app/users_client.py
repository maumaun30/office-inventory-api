"""Client for the Laravel API that owns user records."""

import os
from functools import lru_cache
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError


class ExternalUser(BaseModel):
    id: int
    name: str
    email: str | None = None


class UserPage(BaseModel):
    users: list[ExternalUser]
    page: int
    per_page: int
    total: int | None = None  # None if Laravel didn't send pagination meta
    last_page: int | None = None


class UserNotFound(Exception):
    pass


class UsersServiceError(Exception):
    """Laravel API unreachable, misconfigured, or returned something unexpected."""


class InvalidToken(Exception):
    """Laravel rejected a caller's bearer token."""


class UsersClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    def _send(self, path: str, headers: dict | None = None, **params) -> httpx.Response:
        try:
            return self._http.get(path, params=params or None, headers=headers)
        except httpx.HTTPError as exc:
            raise UsersServiceError(f"Users API unreachable: {exc}") from exc

    @staticmethod
    def _json(resp: httpx.Response) -> dict:
        if resp.is_error:
            raise UsersServiceError(f"Users API returned {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise UsersServiceError("Users API returned invalid JSON") from exc

    def _get(self, path: str, **params) -> dict:
        resp = self._send(path, **params)
        if resp.status_code == 404:
            raise UserNotFound(path)
        return self._json(resp)

    def get_token_owner(self, token: str) -> dict:
        """Resolve a caller's Sanctum token via Laravel's `GET /api/user`.

        Returns the raw user payload so role fields beyond ExternalUser survive.
        """
        resp = self._send("/api/user", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (401, 403):
            raise InvalidToken()
        body = self._json(resp)
        user = body.get("data", body) if isinstance(body, dict) else None
        if not isinstance(user, dict):
            raise UsersServiceError("Unexpected user payload from Users API")
        return user

    def get_user(self, user_id: int) -> ExternalUser:
        body = self._get(f"/api/users/{user_id}")
        try:
            return ExternalUser.model_validate(body.get("data", body))
        except (ValidationError, AttributeError) as exc:
            raise UsersServiceError("Unexpected user payload from Users API") from exc

    def list_users(self, page: int = 1, per_page: int | None = None) -> UserPage:
        params = {"page": page}
        if per_page is not None:
            params["per_page"] = per_page
        body = self._get("/api/users", **params)
        try:
            users = [ExternalUser.model_validate(u) for u in body.get("data", [])]
            meta = body.get("meta") or {}
            return UserPage(
                users=users,
                page=int(meta.get("current_page", page)),
                per_page=int(meta.get("per_page", len(users))),
                total=int(meta["total"]) if "total" in meta else None,
                last_page=int(meta["last_page"]) if "last_page" in meta else None,
            )
        except (ValidationError, AttributeError, TypeError, ValueError) as exc:
            raise UsersServiceError("Unexpected users payload from Users API") from exc

    def ping(self) -> None:
        """Check Laravel's health route (`GET /up`). Raises UsersServiceError if unhealthy."""
        resp = self._send("/up")
        if resp.status_code != 200:
            raise UsersServiceError(f"Users API health check returned {resp.status_code}")


@lru_cache
def get_users_client() -> UsersClient:
    base_url = os.getenv("USERS_API_URL")
    if not base_url:
        raise UsersServiceError("USERS_API_URL is not configured")
    return UsersClient(
        base_url,
        token=_service_token(),
        timeout=float(os.getenv("USERS_API_TIMEOUT", "5")),
    )


def _service_token() -> str | None:
    """USERS_API_TOKEN, or the contents of USERS_API_TOKEN_FILE (e.g. a Docker secret)."""
    if path := os.getenv("USERS_API_TOKEN_FILE"):
        try:
            return Path(path).read_text().strip() or None
        except OSError as exc:
            raise UsersServiceError(f"Cannot read USERS_API_TOKEN_FILE: {exc}") from exc
    return os.getenv("USERS_API_TOKEN")
