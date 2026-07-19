"""WF02 live collector: scrape enabled portals and write feed files for run_job_search."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Must run before anything opens a socket: it loads .env and routes TLS through
# the OS trust store. Without it every portal fetch fails certificate
# verification behind a corporate proxy, and the collectors silently return
# nothing at all.
from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.config_loader import ConfigValidationError, build_runtime_context  # noqa: E402
from src.agent_core.portal_collectors import (  # noqa: E402
    PortalCollectionError,
    collect_portal,
    save_portal_feed,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect live job listings from enabled portals.")
    parser.add_argument("--candidate", default=None)
    parser.add_argument("--output-dir", default="data/job_feeds", help="Where to write <portal>.json feed files")
    parser.add_argument("--max-per-portal", type=int, default=25)
    args = parser.parse_args()

    try:
        ctx = build_runtime_context(REPO_ROOT, candidate_override=args.candidate)
    except ConfigValidationError as exc:
        print(f"[ERROR] {exc}")
        return 1

    profile = ctx["candidate_profile"]
    prefs = ctx["candidate_preferences"]
    target_roles = [r for r in prefs.get("target_roles", []) or [] if str(r).strip()]
    skills = [s for s in profile.get("skills", []) or [] if str(s).strip()]
    if not target_roles:
        print(
            "[WARN] No target_roles set for this candidate - searching on skills alone, "
            "which returns far less relevant results. Set target_roles in "
            f"config/candidates/{ctx.get('candidate_id')}/preferences.json."
        )
    if not skills:
        print(
            "[WARN] Profile has no skills - run WF00 resume ingestion first, or the "
            "search has almost nothing to match on."
        )
    keywords = (target_roles + skills)[:8]
    locations = list(prefs.get("locations", ["Remote"]))
    experience_years = int(profile.get("experience_years", 0) or 0)
    portal_list = ctx.get("portal_list", [])

    output_dir = (REPO_ROOT / args.output_dir).resolve()
    total = 0
    for portal in portal_list:
        print(f"[INFO] Collecting from {portal}...")
        try:
            jobs = collect_portal(portal, keywords, locations, experience_years, args.max_per_portal)
        except PortalCollectionError as exc:
            print(f"[WARN] {portal}: {exc}")
            jobs = []
        feed_path = save_portal_feed(output_dir, portal, jobs)
        print(f"[INFO] {portal}: {len(jobs)} jobs -> {feed_path}")
        total += len(jobs)

    print(f"[OK] Collection complete. Total jobs: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
