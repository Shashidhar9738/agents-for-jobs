from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.pipeline import run_full_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WF01-WF08 pipeline with feed-based WF02 input.")
    parser.add_argument("--candidate", default=None, help="Optional candidate override")
    parser.add_argument(
        "--input-dir",
        default="data/job_feeds",
        help="Directory containing portal job feed files for WF02",
    )
    args = parser.parse_args()

    input_dir = (REPO_ROOT / args.input_dir).resolve() if not Path(args.input_dir).is_absolute() else Path(args.input_dir)
    result = run_full_pipeline(REPO_ROOT, candidate_id=args.candidate, job_feed_input_dir=input_dir)
    print(f"[OK] Full pipeline completed. Processed jobs: {result.processed_jobs}")
    print(f"[INFO] Run context: {result.run_context_path}")
    print(f"[INFO] WF02 output: {result.wf02_output_dir}")
    print(f"[INFO] Dashboard summary: {result.dashboard_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())