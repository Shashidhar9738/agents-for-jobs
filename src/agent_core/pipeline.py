from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from src.agent_core.application_executor import execute_application
from src.agent_core.artifact_store import (
    append_log,
    build_index,
    copy_master_resume,
    resolve_target,
)
from src.agent_core.config_loader import build_runtime_context, persist_runtime_context
from src.agent_core.cover_letter_generator import generate_cover_letter_bundle
from src.agent_core.dashboard import build_dashboard
from src.agent_core.interview_prep import generate_interview_prep
from src.agent_core.job_search import run_job_search, slugify
from src.agent_core.notifications import dispatch_notifications
from src.agent_core.resume_generator import generate_resume_bundle


def _progress(stage: str, message: str) -> None:
    """Announce a stage as it happens.

    The dashboard streams this process's stdout straight into its run log, so
    anything printed here is what the operator watches live. Flush every line:
    a pipe is block-buffered by default and the whole run would otherwise
    arrive at once, after it had already finished.
    """
    print(f"[{stage}] {message}", flush=True)


@dataclass
class FullPipelineResult:
    run_context_path: Path
    wf02_output_dir: Path
    processed_jobs: int
    dashboard_summary_path: Path
    artifact_index_path: Path | None = None


def _collect_live_feeds(run_context: Dict[str, Any], output_dir: Path) -> int:
    """Fetch fresh listings from the enabled portals into the feed directory.

    Without this the pipeline only ever rescores whatever JSON already sits in
    data/job_feeds, which is why a run could report success while finding no
    jobs at all.
    """
    from src.agent_core.portal_collectors import (
        PortalCollectionError,
        collect_portal,
        save_portal_feed,
    )

    profile = run_context.get("candidate_profile") or {}
    preferences = run_context.get("candidate_preferences") or {}
    target_roles = [str(r) for r in (preferences.get("target_roles") or []) if str(r).strip()]
    skills = [str(s) for s in (profile.get("skills") or []) if str(s).strip()]
    keywords = (target_roles + skills)[:8]
    if not keywords:
        _progress("WF02", "No target roles or skills to search on - skipping live collection")
        return 0
    if not target_roles:
        _progress("WF02", "No target_roles set - searching on skills alone, results will be broad")

    locations = [str(loc) for loc in (preferences.get("locations") or ["Remote"])]
    experience_years = int(profile.get("experience_years", 0) or 0)

    total = 0
    for portal in run_context.get("portal_list") or []:
        try:
            jobs = collect_portal(portal, keywords, locations, experience_years, 25)
        except PortalCollectionError as exc:
            _progress("WF02", f"{portal}: collection failed - {exc}")
            continue
        save_portal_feed(output_dir, portal, jobs)
        _progress("WF02", f"{portal}: {len(jobs)} job(s) collected")
        total += len(jobs)
    return total


def run_full_pipeline(
    repo_root: Path,
    candidate_id: str | None,
    job_feed_input_dir: Path,
    collect_live: bool = False,
) -> FullPipelineResult:
    _progress("WF01", "Loading configuration and building run context")
    run_context = build_runtime_context(repo_root, candidate_override=candidate_id)
    run_context_path = persist_runtime_context(repo_root, run_context)
    _progress("WF01", f"Run context ready for candidate '{run_context.get('candidate_id', '')}'")

    if collect_live:
        _progress("WF02", "Collecting live listings from enabled portals")
        found = _collect_live_feeds(run_context, job_feed_input_dir)
        _progress("WF02", f"Live collection wrote {found} job(s) to the feed directory")

    _progress("WF02", "Searching and scoring jobs")
    wf02_result = run_job_search(repo_root, run_context, input_dir=job_feed_input_dir)

    eligible_jobs = json.loads(wf02_result.eligible_jobs_path.read_text(encoding="utf-8"))
    profile_name = _active_profile_name(run_context)
    _progress("WF02", f"{len(eligible_jobs)} job(s) cleared the match threshold")
    processed_jobs = 0
    for index, job in enumerate(eligible_jobs, start=1):
        label = f"{job.get('company', 'unknown')} / {job.get('role_title', 'unknown')}"
        _progress("JOB", f"{index} of {len(eligible_jobs)} - {label}")
        staging_dir = _job_artifact_dir(wf02_result.output_dir, job)

        # Spec section 5 layout: Profiles/<candidate>/<profile>/<company>/<role>/.
        # WF02 stages JD.txt and metadata.json, which seed the browsable folder.
        target = resolve_target(
            repo_root=repo_root,
            candidate_id=str(run_context.get("candidate_id", "")),
            profile_name=profile_name,
            company=str(job.get("company", "unknown")),
            role=str(job.get("role_title", "unknown")),
        )
        artifact_dir = target.directory
        _seed_from_staging(staging_dir, artifact_dir)
        append_log(
            artifact_dir,
            "WF02",
            "resolve_artifact_target",
            "OK",
            f"versioned_rerun={target.is_versioned_rerun}",
        )

        master_resume = _master_resume_path(run_context)
        if master_resume is not None:
            copied = copy_master_resume(artifact_dir, master_resume)
            append_log(
                artifact_dir,
                "WF03",
                "copy_master_resume",
                "OK" if copied else "SKIPPED",
                str(master_resume),
            )

        _progress("WF03", "Generating tailored resume")
        resume_result = generate_resume_bundle(repo_root, run_context, artifact_dir)
        append_log(artifact_dir, "WF03", "generate_resume", "OK", f"mode={resume_result.generation_mode}")
        _progress("WF03", f"Resume written (mode={resume_result.generation_mode})")

        _progress("WF04", "Generating cover letter")
        cover_letter_result = generate_cover_letter_bundle(repo_root, run_context, artifact_dir)
        _progress("WF04", f"Cover letter written (mode={cover_letter_result.generation_mode})")
        append_log(
            artifact_dir,
            "WF04",
            "generate_cover_letter",
            "OK",
            f"mode={cover_letter_result.generation_mode}",
        )

        # Application.json must carry the prompt and model provenance for every
        # generation step that fed it (spec section 10).
        provenance = _merge_provenance(
            [
                ("wf03_resume", resume_result.prompt_versions, resume_result.model_usage),
                ("wf04_cover_letter", cover_letter_result.prompt_versions, cover_letter_result.model_usage),
            ]
        )
        _progress("WF05", "Assembling application and updating the tracker")
        application_result = execute_application(
            repo_root, run_context, artifact_dir, provenance=provenance
        )
        append_log(artifact_dir, "WF05", "execute_application", application_result.status)
        _progress("WF05", f"Application status: {application_result.status}")

        _progress("WF06", "Dispatching notifications")
        dispatch_notifications(repo_root, run_context, artifact_dir)
        append_log(artifact_dir, "WF06", "dispatch_notifications", "OK")

        # Interview prep is the point of the folder for the candidate, so it runs
        # whenever an application was actually submitted.
        if application_result.status == "Applied":
            _progress("WF07", "Generating interview preparation")
            generate_interview_prep(repo_root, run_context, artifact_dir)
            append_log(artifact_dir, "WF07", "generate_interview_prep", "OK")
        else:
            _progress("WF07", f"Skipped - status is '{application_result.status}', not 'Applied'")
        processed_jobs += 1

    _progress("WF08", "Aggregating dashboard summary and artifact index")
    dashboard_result = build_dashboard(repo_root, run_context)
    artifact_index_path = _write_artifact_index(repo_root, run_context)
    _progress("WF08", "Dashboard updated")
    return FullPipelineResult(
        run_context_path=run_context_path,
        wf02_output_dir=wf02_result.output_dir,
        processed_jobs=processed_jobs,
        dashboard_summary_path=dashboard_result.summary_json_path,
        artifact_index_path=artifact_index_path,
    )


def _active_profile_name(run_context: Dict[str, Any]) -> str:
    """Name of the role profile this run targeted, used as a path segment."""
    profile_pack = run_context.get("profile_pack")
    if isinstance(profile_pack, dict):
        selected = profile_pack.get("selected_profiles")
        if isinstance(selected, list) and selected:
            first = selected[0]
            if isinstance(first, dict):
                name = str(first.get("name") or first.get("id") or "").strip()
                if name:
                    return name
    return "default"


def _master_resume_path(run_context: Dict[str, Any]) -> Path | None:
    paths = run_context.get("paths")
    if not isinstance(paths, dict):
        return None
    resume_folder = Path(str(paths.get("resume_folder", "")))
    if not resume_folder.exists():
        return None
    for name in ("resume_master.pdf", "resume_master.docx", "resume_master.txt", "resume_master.md"):
        candidate = resume_folder / name
        if candidate.exists():
            return candidate
    return None


def _seed_from_staging(staging_dir: Path, target_dir: Path) -> None:
    """Move WF02's staged JD and metadata into the browsable target folder."""
    if not staging_dir.exists():
        return
    for name in ("JD.txt", "metadata.json"):
        source = staging_dir / name
        if source.exists() and not (target_dir / name).exists():
            shutil.copy2(source, target_dir / name)


def _write_artifact_index(repo_root: Path, run_context: Dict[str, Any]) -> Path | None:
    """Emit the JSON index the dashboard reads to browse job folders."""
    candidate_id = str(run_context.get("candidate_id", "")).strip()
    if not candidate_id:
        return None
    index = build_index(repo_root, candidate_id)
    destination = repo_root / "output" / candidate_id / "dashboard"
    destination.mkdir(parents=True, exist_ok=True)
    index_path = destination / "artifact_index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index_path


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
    # Must match how WF02 named the folder, so use its own slugifier.
    folder = slugify(f"{job.get('company', 'unknown')}_{job.get('role_title', 'unknown')}")
    return wf02_output_dir / "job_artifacts" / folder