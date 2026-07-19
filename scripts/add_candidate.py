"""Add a new candidate to the platform.

Creates the config, preferences, resume folder, tracker CSV, and (optionally) a
dashboard login, so a new person can be onboarded in one command.

    python scripts/add_candidate.py --id priya --name "Priya Sharma"
    python scripts/add_candidate.py --id priya --name "Priya Sharma" --with-login
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.auth import ROLE_CANDIDATE, AuthError, UserStore  # noqa: E402

TRACKER_HEADER = (
    "Date,CandidateId,Company,Role,Location,JobURL,Source,MatchScore,Status,"
    "Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes\n"
)


def _default_profile(name: str) -> dict:
    """Deliberately empty of facts - WF00 fills these in from the real resume."""
    return {
        "name": name,
        "email": "",
        "phone": "",
        "experience_years": 0,
        "current_title": "",
        "skills": [],
        "locations": ["Remote"],
        "links": {"linkedin": "", "github": "", "portfolio": ""},
    }


def _default_preferences() -> dict:
    return {
        "minimum_match": 70,
        "target_roles": [],
        "locations": ["Remote"],
        "work_modes": ["Remote", "Hybrid"],
        "required_keywords": [],
        "preferred_keywords": [],
        "exclude_keywords": ["intern", "unpaid"],
        "auto_apply": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Onboard a new candidate.")
    parser.add_argument("--id", required=True, help="Short id, e.g. priya (folder and login name)")
    parser.add_argument("--name", required=True, help="Display name, e.g. 'Priya Sharma'")
    parser.add_argument("--with-login", action="store_true", help="Also create a dashboard login")
    parser.add_argument("--make-active", action="store_true", help="Make this the active candidate")
    args = parser.parse_args()

    candidate_id = args.id.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]+", candidate_id):
        print("[FAIL] --id must be lowercase letters, digits, underscore or hyphen only.")
        return 1

    workspace_path = REPO_ROOT / "config" / "workspace.json"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    if candidate_id in workspace.get("candidates", {}):
        print(f"[FAIL] candidate '{candidate_id}' already exists.")
        return 1

    config_dir = REPO_ROOT / "config" / "candidates" / candidate_id
    resume_dir = REPO_ROOT / "data" / "candidates" / candidate_id / "resume"
    output_dir = REPO_ROOT / "output" / candidate_id
    for folder in (config_dir, resume_dir, output_dir):
        folder.mkdir(parents=True, exist_ok=True)

    (config_dir / "profile.json").write_text(
        json.dumps(_default_profile(args.name), indent=2), encoding="utf-8"
    )
    (config_dir / "preferences.json").write_text(
        json.dumps(_default_preferences(), indent=2), encoding="utf-8"
    )
    (resume_dir / "README.txt").write_text(
        f"Place {args.name}'s resume here as resume_master.pdf\n"
        "It is treated as read-only source material and is never edited.\n",
        encoding="utf-8",
    )
    tracker = output_dir / "AppliedJobs.csv"
    if not tracker.exists():
        tracker.write_text(TRACKER_HEADER, encoding="utf-8")

    workspace.setdefault("candidates", {})[candidate_id] = {
        "display_name": args.name,
        "profile_path": f"config/candidates/{candidate_id}/profile.json",
        "preferences_path": f"config/candidates/{candidate_id}/preferences.json",
        "resume_folder": f"data/candidates/{candidate_id}/resume",
        "tracker_csv": f"output/{candidate_id}/AppliedJobs.csv",
    }
    if args.make_active:
        workspace["active_candidate"] = candidate_id
    workspace_path.write_text(json.dumps(workspace, indent=2), encoding="utf-8")

    print(f"[OK] candidate '{candidate_id}' created")
    print(f"     profile      config/candidates/{candidate_id}/profile.json")
    print(f"     preferences  config/candidates/{candidate_id}/preferences.json")
    print(f"     resume       data/candidates/{candidate_id}/resume/")

    if args.with_login:
        password = getpass.getpass(f"Dashboard password for '{candidate_id}': ")
        if len(password) < 8:
            print("[WARN] login not created: password must be at least 8 characters.")
        elif password != getpass.getpass("Confirm password: "):
            print("[WARN] login not created: passwords did not match.")
        else:
            try:
                UserStore(REPO_ROOT / "config" / "users.json").add_user(
                    candidate_id, password, role=ROLE_CANDIDATE, candidate_id=candidate_id
                )
                print(f"[OK] dashboard login '{candidate_id}' created (sees only their own data)")
            except AuthError as exc:
                print(f"[WARN] login not created: {exc}")

    print(f"\nNext: add the resume, then run the pipeline for this candidate.")
    print(f"     data/candidates/{candidate_id}/resume/resume_master.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
