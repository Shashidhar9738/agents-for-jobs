"""Verify this machine is ready to run the job agent.

Run after cloning or pulling on a new system:

    python scripts/check_setup.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OK = "[ OK ]"
MISSING = "[MISS]"
WARN = "[WARN]"


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"{status} {label:<34} {detail}")


def main() -> int:
    print(f"\nJob Agent setup check\n{'-' * 74}")
    problems: list[str] = []

    # --- python packages -------------------------------------------------
    for module, package in [
        ("requests", "requests"),
        ("docx", "python-docx"),
        ("reportlab", "reportlab"),
        ("pypdf", "pypdf"),
        ("cryptography", "cryptography"),
        ("dotenv", "python-dotenv"),
        ("truststore", "truststore"),
    ]:
        try:
            __import__(module)
            _line(OK, f"package: {package}")
        except ImportError:
            _line(MISSING, f"package: {package}", "pip install -r requirements-agent.txt")
            problems.append(f"install {package}")

    print("-" * 74)

    # --- secrets that git intentionally does not carry -------------------
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        _line(OK, ".env present")
        from src.agent_core.bootstrap import load_env_file

        load_env_file(REPO_ROOT)

        if os.getenv("OPENROUTER_API_KEY", "").strip():
            _line(OK, "OPENROUTER_API_KEY set")
        else:
            _line(WARN, "OPENROUTER_API_KEY missing", "AI features fall back to deterministic output")
            problems.append("add OPENROUTER_API_KEY to .env")

        if os.getenv("JOB_AGENT_VAULT_KEY", "").strip():
            _line(OK, "JOB_AGENT_VAULT_KEY set")
        else:
            _line(MISSING, "JOB_AGENT_VAULT_KEY missing", "python scripts/manage_users.py --new-vault-key")
            problems.append("add JOB_AGENT_VAULT_KEY to .env")
    else:
        _line(MISSING, ".env present", "copy it from your other machine, or use .env.example")
        problems.append("create .env")

    users_path = REPO_ROOT / "config" / "users.json"
    if users_path.exists():
        _line(OK, "dashboard logins configured")
    else:
        _line(MISSING, "dashboard logins", "python scripts/manage_users.py --add-admin admin")
        problems.append("create at least one login")

    print("-" * 74)

    # --- candidate inputs ------------------------------------------------
    workspace = REPO_ROOT / "config" / "workspace.json"
    if workspace.exists():
        import json

        candidates = json.loads(workspace.read_text(encoding="utf-8")).get("candidates", {})
        for candidate_id in candidates:
            folder = REPO_ROOT / "data" / "candidates" / candidate_id / "resume"
            found = next(
                (p for p in folder.glob("resume_master.*") if p.is_file()), None
            ) if folder.exists() else None
            if found:
                _line(OK, f"master resume: {candidate_id}", found.name)
            else:
                _line(WARN, f"master resume: {candidate_id}", f"add resume_master.pdf to {folder}")
    else:
        _line(MISSING, "config/workspace.json")
        problems.append("workspace config missing")

    print("-" * 74)
    if problems:
        print(f"\n{len(problems)} item(s) to fix:\n")
        for item in problems:
            print(f"  - {item}")
        print("\nThen run: python scripts/serve_dashboard.py\n")
        return 1

    print("\nEverything is ready. Start with:\n\n    python scripts/serve_dashboard.py\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
