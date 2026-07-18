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
from src.agent_core.resume_generator import ResumeGenerationError, generate_resume_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WF03 resume generation for a single job artifact directory.")
    parser.add_argument("--candidate", default=None, help="Optional candidate override when no run context file is supplied")
    parser.add_argument("--run-context", default=None, help="Optional path to a runtime context JSON file")
    parser.add_argument(
        "--job-artifact-dir",
        required=True,
        help="Directory containing JD.txt and metadata.json from WF02",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional explicit output directory for Resume.pdf, Resume.docx, and resume.json",
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

    job_artifact_dir = (REPO_ROOT / args.job_artifact_dir).resolve() if not Path(args.job_artifact_dir).is_absolute() else Path(args.job_artifact_dir)
    output_dir = None
    if args.output_dir:
        output_dir = (REPO_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    try:
        result = generate_resume_bundle(REPO_ROOT, run_context, job_artifact_dir=job_artifact_dir, output_dir=output_dir)
    except ResumeGenerationError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"[OK] WF03 completed for candidate: {run_context['candidate_id']}")
    print(f"[INFO] Output directory: {result.output_dir}")
    print(f"[INFO] resume.json: {result.resume_json_path}")
    print(f"[INFO] Resume.docx: {result.resume_docx_path}")
    print(f"[INFO] Resume.pdf: {result.resume_pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())