from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from src.agent_core.auth import ROLE_ADMIN, ROLE_CANDIDATE, AuthError, UserStore

TRACKER_HEADER = (
    "Date,CandidateId,Company,Role,Location,JobURL,Source,MatchScore,Status,"
    "Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes\n"
)

# Set in .env to require a shared code before anyone can self-register. Strongly
# recommended before this is reachable from anything but localhost.
REGISTRATION_CODE_ENV = "JOB_AGENT_REGISTRATION_CODE"
REGISTRATION_OPEN_ENV = "JOB_AGENT_ALLOW_OPEN_REGISTRATION"

MIN_PASSWORD_LENGTH = 8
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")

# Rejected outright - these are the first guesses in any credential-stuffing list.
_WEAK_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "qwerty123",
    "changeme", "changeme123", "letmein1", "welcome1", "admin123", "iloveyou",
}


class RegistrationError(ValueError):
    """Raised when a registration request is invalid or not permitted."""


@dataclass
class RegistrationResult:
    candidate_id: str
    display_name: str
    role: str
    is_first_user: bool


def registration_state(repo_root: Path) -> Dict[str, Any]:
    """Describe how registration behaves right now, for the sign-up page."""
    store = UserStore(repo_root / "config" / "users.json")
    has_users = store.exists()
    code_required = bool(os.getenv(REGISTRATION_CODE_ENV, "").strip())
    open_registration = os.getenv(REGISTRATION_OPEN_ENV, "").strip().lower() in {"1", "true", "yes"}
    return {
        # The very first account is always allowed, otherwise nobody could start.
        "enabled": (not has_users) or code_required or open_registration,
        "code_required": code_required and has_users,
        "first_user": not has_users,
        "open": open_registration,
    }


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise RegistrationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.strip().lower() in _WEAK_PASSWORDS:
        raise RegistrationError("That password is too common. Choose something less guessable.")


def register_candidate(
    repo_root: Path,
    candidate_id: str,
    display_name: str,
    password: str,
    registration_code: str = "",
) -> RegistrationResult:
    """Create a candidate and their login in one step.

    The first account created becomes the admin, so a fresh install is usable
    without a terminal. Every later account is candidate-scoped and can only
    ever see its own data.
    """
    state = registration_state(repo_root)
    if not state["enabled"]:
        raise RegistrationError(
            "Registration is closed. Ask an admin to create the account, or set "
            f"{REGISTRATION_CODE_ENV} in .env to allow sign-ups."
        )

    if state["code_required"]:
        expected = os.getenv(REGISTRATION_CODE_ENV, "").strip()
        if not registration_code or registration_code.strip() != expected:
            raise RegistrationError("Invalid registration code.")

    candidate_id = (candidate_id or "").strip().lower()
    display_name = (display_name or "").strip()
    if not _ID_PATTERN.fullmatch(candidate_id):
        raise RegistrationError(
            "Username must be 2-30 characters, lowercase letters, digits, '-' or '_'."
        )
    if not display_name:
        raise RegistrationError("Full name is required.")
    validate_password(password)

    workspace_path = repo_root / "config" / "workspace.json"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    if candidate_id in workspace.get("candidates", {}):
        raise RegistrationError(f"'{candidate_id}' is already taken.")

    store = UserStore(repo_root / "config" / "users.json")
    if any(user.username == candidate_id for user in store.list_users()):
        raise RegistrationError(f"'{candidate_id}' is already taken.")

    role = ROLE_ADMIN if state["first_user"] else ROLE_CANDIDATE
    try:
        store.add_user(
            candidate_id,
            password,
            role=role,
            candidate_id=candidate_id,
        )
    except AuthError as exc:
        raise RegistrationError(str(exc)) from exc

    _scaffold_candidate(repo_root, candidate_id, display_name, workspace, workspace_path)

    return RegistrationResult(
        candidate_id=candidate_id,
        display_name=display_name,
        role=role,
        is_first_user=state["first_user"],
    )


def _scaffold_candidate(
    repo_root: Path,
    candidate_id: str,
    display_name: str,
    workspace: Dict[str, Any],
    workspace_path: Path,
) -> None:
    """Create the folders and config a candidate needs to be runnable."""
    config_dir = repo_root / "config" / "candidates" / candidate_id
    resume_dir = repo_root / "data" / "candidates" / candidate_id / "resume"
    output_dir = repo_root / "output" / candidate_id
    for folder in (config_dir, resume_dir, output_dir):
        folder.mkdir(parents=True, exist_ok=True)

    # Left empty on purpose: WF00 fills these from the real resume, so no
    # placeholder detail can ever reach a generated CV.
    (config_dir / "profile.json").write_text(
        json.dumps(
            {
                "name": display_name,
                "email": "",
                "phone": "",
                "experience_years": 0,
                "current_title": "",
                "skills": [],
                "locations": ["Remote"],
                "links": {"linkedin": "", "github": "", "portfolio": ""},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (config_dir / "preferences.json").write_text(
        json.dumps(
            {
                "minimum_match": 70,
                "target_roles": [],
                "locations": ["Remote"],
                "work_modes": ["Remote", "Hybrid"],
                "required_keywords": [],
                "preferred_keywords": [],
                "exclude_keywords": ["intern", "unpaid"],
                "auto_apply": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (resume_dir / "README.txt").write_text(
        f"Place {display_name}'s resume here as resume_master.pdf\n"
        "It is read-only source material and is never edited by the agent.\n",
        encoding="utf-8",
    )
    tracker = output_dir / "AppliedJobs.csv"
    if not tracker.exists():
        tracker.write_text(TRACKER_HEADER, encoding="utf-8")

    workspace.setdefault("candidates", {})[candidate_id] = {
        "display_name": display_name,
        "profile_path": f"config/candidates/{candidate_id}/profile.json",
        "preferences_path": f"config/candidates/{candidate_id}/preferences.json",
        "resume_folder": f"data/candidates/{candidate_id}/resume",
        "tracker_csv": f"output/{candidate_id}/AppliedJobs.csv",
    }
    workspace.setdefault("active_candidate", candidate_id)
    workspace_path.write_text(json.dumps(workspace, indent=2), encoding="utf-8")
