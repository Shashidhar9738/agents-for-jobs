from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from src.agent_core.application_executor import execute_application
from src.agent_core.config_loader import build_runtime_context, persist_runtime_context
from src.agent_core.cover_letter_generator import generate_cover_letter_bundle
from src.agent_core.dashboard import build_dashboard
from src.agent_core.interview_prep import generate_interview_prep
from src.agent_core.job_search import run_job_search
from src.agent_core.notifications import dispatch_notifications
from src.agent_core.resume_generator import generate_resume_bundle


@dataclass
class FullPipelineResult:
    run_context_path: Path
    wf02_output_dir: Path
    processed_jobs: int
    dashboard_summary_path: Path


def run_full_pipeline(
    repo_root: Path,
    candidate_id: str | None,
    job_feed_input_dir: Path,
) -> FullPipelineResult:
    run_context = build_runtime_context(repo_root, candidate_override=candidate_id)
    run_context_path = persist_runtime_context(repo_root, run_context)
    wf02_result = run_job_search(repo_root, run_context, input_dir=job_feed_input_dir)

    eligible_jobs = json.loads(wf02_result.eligible_jobs_path.read_text(encoding="utf-8"))
    processed_jobs = 0
    for job in eligible_jobs:
        artifact_dir = _job_artifact_dir(wf02_result.output_dir, job)
        generate_resume_bundle(repo_root, run_context, artifact_dir)
        generate_cover_letter_bundle(repo_root, run_context, artifact_dir)
        application_result = execute_application(repo_root, run_context, artifact_dir)
        dispatch_notifications(repo_root, run_context, artifact_dir)
        if application_result.status == "Applied":
            generate_interview_prep(repo_root, run_context, artifact_dir)
        processed_jobs += 1

    dashboard_result = build_dashboard(repo_root, run_context)
    return FullPipelineResult(
        run_context_path=run_context_path,
        wf02_output_dir=wf02_result.output_dir,
        processed_jobs=processed_jobs,
        dashboard_summary_path=dashboard_result.summary_json_path,
    )


def _job_artifact_dir(wf02_output_dir: Path, job: Dict[str, Any]) -> Path:
    company = str(job.get("company", "unknown")).strip().lower()
    role = str(job.get("role_title", "unknown")).strip().lower()
    slug = "_".join(part for part in [company, role] if part)
    slug = "".join(character if character.isalnum() else "_" for character in slug).strip("_") or "job"
    return wf02_output_dir / "job_artifacts" / slug