from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.config_loader import ConfigValidationError, build_runtime_context
from src.agent_core.job_search import JobSearchError, run_job_search


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WF02 job search from a runtime context or candidate config.")
    parser.add_argument("--candidate", default=None, help="Optional candidate override when no run context file is supplied")
    parser.add_argument(
        "--run-context",
        default=None,
        help="Path to a runtime context JSON file. If omitted, a fresh context is built from config.",
    )
    parser.add_argument(
        "--input-dir",
        default="data/job_feeds",
        help="Directory containing per-portal job feed files such as linkedin.json or indeed.csv",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional explicit output directory. Defaults to output/<candidate>/wf02/<run_id>/",
    )
    args = parser.parse_args()

    try:
        if args.run_context:
            run_context_path = (REPO_ROOT / args.run_context).resolve() if not Path(args.run_context).is_absolute() else Path(args.run_context)
            run_context = json.loads(run_context_path.read_text(encoding="utf-8"))
        else:
            run_context = build_runtime_context(REPO_ROOT, candidate_override=args.candidate)
    except (ConfigValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Unable to load runtime context: {exc}")
        return 1

    input_dir = (REPO_ROOT / args.input_dir).resolve() if not Path(args.input_dir).is_absolute() else Path(args.input_dir)
    output_dir = None
    if args.output_dir:
        output_dir = (REPO_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    try:
        result = run_job_search(REPO_ROOT, run_context, input_dir=input_dir, output_dir=output_dir)
    except JobSearchError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"[OK] WF02 completed for candidate: {run_context['candidate_id']}")
    print(f"[INFO] Output directory: {result.output_dir}")
    print(f"[INFO] Jobs normalized: {result.jobs_normalized_path}")
    print(f"[INFO] Eligible jobs: {result.eligible_jobs_path}")
    print(
        f"[INFO] Decisions: Apply={result.apply_count}, Review={result.review_count}, Skip={result.skip_count}, Total={result.total_jobs}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())