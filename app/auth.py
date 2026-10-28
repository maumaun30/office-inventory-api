"""Bearer-token auth backed by the Laravel API (Sanctum).

Callers send their own Sanctum token; it is resolved via Laravel's
`GET /api/user` and cached briefly so each request doesn't hit Laravel.
"""

import hashlib
import os
import threading
import time
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from app.deps import Users
from app.users_client import InvalidToken, UsersServiceError


class CurrentUser(BaseModel):
    id: int
    name: str
    email: str | None = None
    is_admin: bool = False


class AuthSettings(BaseModel):
    admin_field: str = "role"
    admin_values: frozenset[str] = frozenset({"admin"})
    cache_ttl: float = 60.0


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings(
        admin_field=os.getenv("AUTH_ADMIN_FIELD", "role"),
        admin_values=frozenset(
            v.strip() for v in os.getenv("AUTH_ADMIN_VALUES", "admin").split(",") if v.strip()
        ),
        cache_ttl=float(os.getenv("AUTH_CACHE_TTL", "60")),
    )


def is_admin(value: Any, admin_values: frozenset[str]) -> bool:
    """Interpret a Laravel role field.

    Handles `true`, `"admin"`, `["admin", ...]`, and Spatie-style
    `[{"name": "admin"}, ...]`.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value in admin_values
    if isinstance(value, list):
        names = (v.get("name") if isinstance(v, dict) else v for v in value)
        return any(isinstance(n, str) and n in admin_values for n in names)
    return False


class TokenCache:
    """In-process TTL cache of token hash -> CurrentUser. Only successes are cached."""

    max_entries = 10_000

    def __init__(self):
        self._entries: dict[str, tuple[float, CurrentUser]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> CurrentUser | None:
        with self._lock:
            entry = self._entries.get(self._key(token))
            if entry is None:
                return None
            expires, user = entry
            if expires < time.monotonic():
                del self._entries[self._key(token)]
                return None
            return user

    def set(self, token: str, user: CurrentUser, ttl: float) -> None:
        if ttl <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self.max_entries:
                self._entries = {k: v for k, v in self._entries.items() if v[0] >= now}
                if len(self._entries) >= self.max_entries:
                    self._entries.clear()
            self._entries[self._key(token)] = (now + ttl, user)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


token_cache = TokenCache()
bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def current_user(
    users: Users,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not authenticated")
    token = credentials.credentials
    if cached := token_cache.get(token):
        return cached

    settings = get_auth_settings()
    try:
        raw = users.get_token_owner(token)
    except InvalidToken:
        raise _unauthorized("Invalid or expired token") from None
    try:
        user = CurrentUser(
            id=raw["id"],
            name=raw["name"],
            email=raw.get("email"),
            is_admin=is_admin(raw.get(settings.admin_field), settings.admin_values),
        )
    except (KeyError, ValidationError) as exc:
        raise UsersServiceError("Unexpected user payload from Users API") from exc
    token_cache.set(token, user, settings.cache_ttl)
    return user


Authenticated = Annotated[CurrentUser, Depends(current_user)]


def require_admin(user: Authenticated) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


Admin = Annotated[CurrentUser, Depends(require_admin)]

# For route/router `dependencies=[...]` where the user object isn't needed.
authenticated = Depends(current_user)
admin_only = Depends(require_admin)
