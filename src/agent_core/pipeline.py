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
        resume_result = generate_resume_bundle(repo_root, run_context, artifact_dir)
        cover_letter_result = generate_cover_letter_bundle(repo_root, run_context, artifact_dir)

        # Application.json must carry the prompt and model provenance for every
        # generation step that fed it (spec section 10).
        provenance = _merge_provenance(
            [
                ("wf03_resume", resume_result.prompt_versions, resume_result.model_usage),
                ("wf04_cover_letter", cover_letter_result.prompt_versions, cover_letter_result.model_usage),
            ]
        )
        application_result = execute_application(
            repo_root, run_context, artifact_dir, provenance=provenance
        )
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


def _merge_provenance(
    stages: List[tuple[str, Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    """Combine per-stage prompt versions and model usage into one provenance block."""
    prompt_versions: Dict[str, Any] = {}
    per_stage_usage: Dict[str, Any] = {}
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    for stage_name, stage_prompts, stage_usage in stages:
        for prompt_key, prompt_meta in stage_prompts.items():
            prompt_versions[prompt_key] = prompt_meta
        if stage_usage:
            per_stage_usage[stage_name] = stage_usage
            total_prompt_tokens += int(stage_usage.get("prompt_tokens", 0))
            total_completion_tokens += int(stage_usage.get("completion_tokens", 0))
            total_cost += float(stage_usage.get("estimated_cost_usd", 0.0))

    return {
        "prompt_versions": prompt_versions,
        "model_usage": {
            "stages": per_stage_usage,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "total_estimated_cost_usd": round(total_cost, 6),
        },
    }


def _job_artifact_dir(wf02_output_dir: Path, job: Dict[str, Any]) -> Path:
    company = str(job.get("company", "unknown")).strip().lower()
    role = str(job.get("role_title", "unknown")).strip().lower()
    slug = "_".join(part for part in [company, role] if part)
    slug = "".join(character if character.isalnum() else "_" for character in slug).strip("_") or "job"
    return wf02_output_dir / "job_artifacts" / slug