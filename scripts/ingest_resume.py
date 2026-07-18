"""Derive a candidate profile from their master resume.

    python scripts/ingest_resume.py --candidate shashi
    python scripts/ingest_resume.py --candidate shashi --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.config_loader import build_runtime_context  # noqa: E402
from src.agent_core.resume_ingest import ResumeIngestError, ingest_master_resume  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate a candidate profile from their master resume.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    try:
        context = build_runtime_context(REPO_ROOT, candidate_override=args.candidate)
        result = ingest_master_resume(REPO_ROOT, args.candidate, context, write=not args.dry_run)
    except ResumeIngestError as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(f"[OK] Read {result.source_resume.name} (extraction: {result.extraction_mode})")
    print(f"[INFO] Fields updated: {', '.join(result.fields_updated) or 'none'}")
    print(f"[INFO] Skills found ({len(result.skills_found)}): {', '.join(result.skills_found) or 'none'}")

    if result.rejected_skills:
        print(
            f"[GUARD] Dropped {len(result.rejected_skills)} skill(s) not present in the resume: "
            f"{', '.join(result.rejected_skills)}"
        )
    if result.model_usage:
        print(f"[INFO] Model usage: {result.model_usage}")
    if args.dry_run:
        print("[INFO] Dry run - profile.json was not modified.")
    else:
        print(f"[INFO] Profile written: {result.profile_path}")
        if result.backup_path:
            print(f"[INFO] Previous profile archived: {result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
