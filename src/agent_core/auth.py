from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class AuthError(ValueError):
    """Raised when authentication configuration or credentials are invalid."""


# PBKDF2 cost. Raise over time; stored hashes record the value used so old
# records keep verifying after the default changes.
_PBKDF2_ITERATIONS = 480_000
_SESSION_TTL_SECONDS = 8 * 60 * 60

ROLE_ADMIN = "admin"
ROLE_CANDIDATE = "candidate"

MIN_PASSWORD_LENGTH = 8


def validate_password(password: str) -> None:
    """Raise AuthError if a proposed password fails policy.

    Kept here rather than at the call sites so the CLI, the registration flow,
    and the dashboard reset routes cannot drift apart on what they accept.
    """
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")


@dataclass
class User:
    username: str
    role: str
    candidate_id: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def can_access(self, candidate_id: str) -> bool:
        """Admins see everyone; a candidate sees only their own records."""
        return self.is_admin or self.candidate_id == candidate_id

    def as_public(self) -> Dict[str, Any]:
        return {"username": self.username, "role": self.role, "candidate_id": self.candidate_id}


def hash_password(password: str, salt: bytes | None = None, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Return a self-describing PBKDF2 hash: pbkdf2_sha256$iterations$salt$digest."""
    if not password:
        raise AuthError("password must not be empty")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against a stored hash."""
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


class UserStore:
    """File-backed user registry. Passwords are only ever stored hashed."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"users": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def exists(self) -> bool:
        return self.path.exists() and bool(self._read().get("users"))

    def list_users(self) -> List[User]:
        return [
            User(
                username=record["username"],
                role=record.get("role", ROLE_CANDIDATE),
                candidate_id=record.get("candidate_id"),
            )
            for record in self._read().get("users", [])
        ]

    def add_user(
        self,
        username: str,
        password: str,
        role: str = ROLE_CANDIDATE,
        candidate_id: str | None = None,
    ) -> User:
        username = username.strip().lower()
        if not username:
            raise AuthError("username must not be empty")
        if role not in (ROLE_ADMIN, ROLE_CANDIDATE):
            raise AuthError(f"unknown role '{role}'")
        if role == ROLE_CANDIDATE and not candidate_id:
            raise AuthError("a candidate user must be linked to a candidate_id")

        payload = self._read()
        users = payload.setdefault("users", [])
        if any(record["username"] == username for record in users):
            raise AuthError(f"user '{username}' already exists")

        users.append(
            {
                "username": username,
                "password_hash": hash_password(password),
                "role": role,
                "candidate_id": candidate_id,
            }
        )
        self._write(payload)
        return User(username=username, role=role, candidate_id=candidate_id)

    def set_password(self, username: str, password: str) -> None:
        validate_password(password)
        payload = self._read()
        for record in payload.get("users", []):
            if record["username"] == username.strip().lower():
                record["password_hash"] = hash_password(password)
                self._write(payload)
                return
        raise AuthError(f"user '{username}' not found")

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        """Self-serve change: proves knowledge of the current password first.

        Distinct from set_password, which is the admin override and deliberately
        does not require the old password.
        """
        if self.authenticate(username, current_password) is None:
            raise AuthError("current password is incorrect")
        if current_password == new_password:
            raise AuthError("new password must be different from the current one")
        self.set_password(username, new_password)

    def authenticate(self, username: str, password: str) -> User | None:
        username = (username or "").strip().lower()
        for record in self._read().get("users", []):
            if record["username"] == username:
                if verify_password(password or "", record.get("password_hash", "")):
                    return User(
                        username=record["username"],
                        role=record.get("role", ROLE_CANDIDATE),
                        candidate_id=record.get("candidate_id"),
                    )
                return None
        # Spend comparable time on unknown users so timing does not leak existence.
        verify_password(password or "", hash_password("dummy"))
        return None


API_TOKEN_ENV = "JOB_AGENT_API_TOKEN"


def machine_user_from_token(token: str | None) -> User | None:
    """Authenticate a service caller (n8n) via a shared API token.

    Browser sessions are unsuitable for workflow engines, so a single token in
    the environment grants machine access. It is admin-scoped because the
    orchestrator runs stages for every candidate; keep it out of source control.
    """
    import os

    expected = os.getenv(API_TOKEN_ENV, "").strip()
    if not expected or not token:
        return None
    if not hmac.compare_digest(token.strip(), expected):
        return None
    return User(username="n8n", role=ROLE_ADMIN, candidate_id=None)


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


class SessionStore:
    """In-memory sessions. Cleared on restart, which is fine for a local tool."""

    def __init__(self, ttl_seconds: int = _SESSION_TTL_SECONDS) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def create(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {"user": user, "expires_at": time.time() + self._ttl}
        return token

    def get(self, token: str | None) -> User | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        if session["expires_at"] < time.time():
            self._sessions.pop(token, None)
            return None
        return session["user"]

    def destroy(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def destroy_for_user(self, username: str, keep_token: str | None = None) -> int:
        """Drop every session for a user, optionally sparing the caller's own.

        Called after a password change so a stolen or stale session cannot
        outlive the credential it was issued against.
        """
        doomed = [
            token
            for token, session in self._sessions.items()
            if session["user"].username == username and token != keep_token
        ]
        for token in doomed:
            self._sessions.pop(token, None)
        return len(doomed)
