from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from cryptography.fernet import Fernet, InvalidToken


class VaultError(ValueError):
    """Raised when the credential vault cannot be opened or written."""


VAULT_KEY_ENV = "JOB_AGENT_VAULT_KEY"


def generate_key() -> str:
    """Create a new vault key for JOB_AGENT_VAULT_KEY."""
    return Fernet.generate_key().decode("ascii")


def _load_key() -> Fernet:
    raw = os.getenv(VAULT_KEY_ENV, "").strip()
    if not raw:
        raise VaultError(
            f"{VAULT_KEY_ENV} is not set. Generate one with "
            "`python scripts/manage_users.py --new-vault-key` and add it to .env."
        )
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise VaultError(f"{VAULT_KEY_ENV} is not a valid Fernet key") from exc


class CredentialVault:
    """Per-candidate portal credentials, encrypted at rest.

    Only the password field is encrypted; usernames stay readable so the UI can
    show which account is configured without unlocking anything. Passwords are
    never returned to the browser - callers get a masked view.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"candidates": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VaultError(f"vault file is corrupt: {self.path}") from exc

    def _write(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def set_credential(
        self,
        candidate_id: str,
        portal: str,
        username: str,
        password: str,
        extra: Dict[str, Any] | None = None,
    ) -> None:
        if not candidate_id or not portal:
            raise VaultError("candidate_id and portal are required")

        fernet = _load_key()
        payload = self._read()
        candidates = payload.setdefault("candidates", {})
        entries = candidates.setdefault(candidate_id, {})

        entries[portal] = {
            "username": username,
            "password_encrypted": fernet.encrypt(password.encode("utf-8")).decode("ascii")
            if password
            else "",
            "extra": extra or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
            # Lets the UI warn if a stored password no longer decrypts because
            # the vault key was rotated.
            "key_fingerprint": _key_fingerprint(),
        }
        self._write(payload)

    def delete_credential(self, candidate_id: str, portal: str) -> bool:
        payload = self._read()
        entries = payload.get("candidates", {}).get(candidate_id, {})
        if portal not in entries:
            return False
        entries.pop(portal)
        self._write(payload)
        return True

    def get_password(self, candidate_id: str, portal: str) -> str:
        """Decrypt one password. Used by the application executor, never by the UI."""
        entry = self._read().get("candidates", {}).get(candidate_id, {}).get(portal)
        if not entry:
            raise VaultError(f"no credential stored for {candidate_id}/{portal}")

        encrypted = entry.get("password_encrypted", "")
        if not encrypted:
            return ""
        try:
            return _load_key().decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise VaultError(
                f"stored password for {candidate_id}/{portal} cannot be decrypted - "
                f"the vault key changed. Re-enter this credential."
            ) from exc

    def list_masked(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Safe view for the browser: no secrets, only presence and freshness."""
        entries = self._read().get("candidates", {}).get(candidate_id, {})
        current = _key_fingerprint()
        result: List[Dict[str, Any]] = []
        for portal, entry in sorted(entries.items()):
            stored_fingerprint = entry.get("key_fingerprint", "")
            result.append(
                {
                    "portal": portal,
                    "username": entry.get("username", ""),
                    "has_password": bool(entry.get("password_encrypted")),
                    "updated_at": entry.get("updated_at", ""),
                    "needs_reentry": bool(stored_fingerprint and stored_fingerprint != current),
                }
            )
        return result

    def configured_portals(self, candidate_id: str) -> List[str]:
        return sorted(self._read().get("candidates", {}).get(candidate_id, {}).keys())


def _key_fingerprint() -> str:
    """Short non-reversible tag identifying which key encrypted an entry."""
    raw = os.getenv(VAULT_KEY_ENV, "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12] if raw else ""


def mask_secret(value: str) -> str:
    """Render a secret for display without revealing it."""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * (len(value) - 2) + value[-2:]


__all__ = [
    "CredentialVault",
    "VaultError",
    "VAULT_KEY_ENV",
    "generate_key",
    "mask_secret",
    "base64",
]
