"""Create dashboard logins and the credential-vault key.

    python scripts/manage_users.py --new-vault-key
    python scripts/manage_users.py --add-admin admin
    python scripts/manage_users.py --add-candidate shashi --candidate-id shashi
    python scripts/manage_users.py --list
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.auth import ROLE_ADMIN, ROLE_CANDIDATE, AuthError, UserStore  # noqa: E402
from src.agent_core.vault import VAULT_KEY_ENV, generate_key  # noqa: E402

USERS_PATH = REPO_ROOT / "config" / "users.json"


def _prompt_password(username: str) -> str:
    first = getpass.getpass(f"Password for '{username}': ")
    if len(first) < 8:
        print("[FAIL] Password must be at least 8 characters.")
        raise SystemExit(1)
    if first != getpass.getpass("Confirm password: "):
        print("[FAIL] Passwords did not match.")
        raise SystemExit(1)
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage dashboard users and the vault key.")
    parser.add_argument("--add-admin", metavar="USERNAME")
    parser.add_argument("--add-candidate", metavar="USERNAME")
    parser.add_argument("--candidate-id", metavar="ID", help="Candidate this login may view")
    parser.add_argument("--set-password", metavar="USERNAME")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--new-vault-key", action="store_true")
    args = parser.parse_args()

    store = UserStore(USERS_PATH)

    if args.new_vault_key:
        print("Add this line to your .env file (keep it secret, never commit it):\n")
        print(f"{VAULT_KEY_ENV}={generate_key()}")
        print(
            "\nWARNING: if this key is lost or changed, stored portal passwords "
            "cannot be decrypted and must be re-entered."
        )
        return 0

    try:
        if args.add_admin:
            store.add_user(args.add_admin, _prompt_password(args.add_admin), role=ROLE_ADMIN)
            print(f"[OK] Admin '{args.add_admin}' created. Admins can see every candidate.")
            return 0

        if args.add_candidate:
            candidate_id = args.candidate_id or args.add_candidate
            store.add_user(
                args.add_candidate,
                _prompt_password(args.add_candidate),
                role=ROLE_CANDIDATE,
                candidate_id=candidate_id,
            )
            print(f"[OK] Candidate login '{args.add_candidate}' created for '{candidate_id}'.")
            return 0

        if args.set_password:
            store.set_password(args.set_password, _prompt_password(args.set_password))
            print(f"[OK] Password updated for '{args.set_password}'.")
            return 0
    except AuthError as exc:
        print(f"[FAIL] {exc}")
        return 1

    if args.list or True:
        users = store.list_users()
        if not users:
            print("No users yet. Create one with --add-admin or --add-candidate.")
            return 0
        print(f"{'USERNAME':<20} {'ROLE':<12} CANDIDATE")
        for user in users:
            print(f"{user.username:<20} {user.role:<12} {user.candidate_id or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
