from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.config_loader import ConfigValidationError, build_runtime_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Build runtime context from workspace configuration.")
    parser.add_argument(
        "--candidate",
        help="Override active candidate id from config/workspace.json",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="Optional output path for generated context JSON",
        default="logs/run_context.json",
    )
    args = parser.parse_args()

    repo_root = REPO_ROOT
    try:
        context = build_runtime_context(repo_root, candidate_override=args.candidate)
    except ConfigValidationError as exc:
        print(f"[ERROR] {exc}")
        return 1

    output_path = (repo_root / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(context, indent=2), encoding="utf-8")

    print(f"[OK] Runtime context generated: {output_path}")
    print(f"[INFO] Candidate: {context['candidate_id']}")
    print(f"[INFO] Run ID: {context['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
