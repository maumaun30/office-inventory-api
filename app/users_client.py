"""Client for the Laravel API that owns user records."""

import os
from functools import lru_cache

import httpx
from pydantic import BaseModel, ValidationError


class ExternalUser(BaseModel):
    id: int
    name: str
    email: str | None = None


class UserNotFound(Exception):
    pass


class UsersServiceError(Exception):
    """Laravel API unreachable, misconfigured, or returned something unexpected."""


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

    def _get(self, path: str, **params) -> dict:
        try:
            resp = self._http.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise UsersServiceError(f"Users API unreachable: {exc}") from exc
        if resp.status_code == 404:
            raise UserNotFound(path)
        if resp.is_error:
            raise UsersServiceError(f"Users API returned {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise UsersServiceError("Users API returned invalid JSON") from exc

    def get_user(self, user_id: int) -> ExternalUser:
        body = self._get(f"/api/users/{user_id}")
        try:
            return ExternalUser.model_validate(body.get("data", body))
        except (ValidationError, AttributeError) as exc:
            raise UsersServiceError("Unexpected user payload from Users API") from exc

    def list_users(self, page: int = 1) -> list[ExternalUser]:
        body = self._get("/api/users", page=page)
        try:
            return [ExternalUser.model_validate(u) for u in body.get("data", [])]
        except (ValidationError, AttributeError) as exc:
            raise UsersServiceError("Unexpected users payload from Users API") from exc


@lru_cache
def get_users_client() -> UsersClient:
    base_url = os.getenv("USERS_API_URL")
    if not base_url:
        raise UsersServiceError("USERS_API_URL is not configured")
    return UsersClient(
        base_url,
        token=os.getenv("USERS_API_TOKEN"),
        timeout=float(os.getenv("USERS_API_TIMEOUT", "5")),
    )
