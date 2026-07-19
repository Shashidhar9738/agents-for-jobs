from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.agent_core.application_executor import execute_application
from src.agent_core.artifact_store import append_log, build_index, copy_master_resume, resolve_target
from src.agent_core.config_loader import build_runtime_context, persist_runtime_context
from src.agent_core.cover_letter_generator import generate_cover_letter_bundle
from src.agent_core.dashboard import build_dashboard
from src.agent_core.interview_prep import generate_interview_prep
from src.agent_core.job_search import run_job_search
from src.agent_core.notifications import dispatch_notifications
from src.agent_core.resume_generator import generate_resume_bundle
from src.agent_core.resume_ingest import find_master_resume, ingest_master_resume


class StageError(ValueError):
    """Raised when a stage cannot run with the supplied input."""


# Each stage is individually callable so an n8n workflow can own one step,
# keeping retries, error branches, and run history visible on the canvas.
STAGE_ORDER: List[str] = ["wf00", "wf01", "wf02", "wf03", "wf04", "wf05", "wf06", "wf07", "wf08"]

STAGE_LABELS: Dict[str, str] = {
    "wf00": "Resume ingestion",
    "wf01": "Configuration loader",
    "wf02": "Job search and scoring",
    "wf03": "Resume generator",
    "wf04": "Cover letter generator",
    "wf05": "Application executor",
    "wf06": "Notifications",
    "wf07": "Interview preparation",
    "wf08": "Dashboard aggregation",
}


def _context(repo_root: Path, candidate_id: str) -> Dict[str, Any]:
    return build_runtime_context(repo_root, candidate_override=candidate_id)


def _artifact_dirs(repo_root: Path, candidate_id: str) -> List[Path]:
    """Job folders for this candidate, newest first."""
    index = build_index(repo_root, candidate_id)
    return [Path(target["directory"]) for target in index.get("targets", [])]


def _profile_name(context: Dict[str, Any]) -> str:
    pack = context.get("profile_pack") or {}
    selected = pack.get("selected_profiles") or []
    if selected and isinstance(selected[0], dict):
        return str(selected[0].get("name") or selected[0].get("id") or "default")
    return "default"


def run_stage(repo_root: Path, stage: str, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one pipeline stage and return a JSON-serialisable summary."""
    stage = stage.lower().strip()
    handler = _HANDLERS.get(stage)
    if handler is None:
        raise StageError(f"unknown stage '{stage}'. Known: {', '.join(STAGE_ORDER)}")

    started = datetime.now(timezone.utc)
    result = handler(repo_root, candidate_id, payload or {})
    result.update(
        {
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "candidate_id": candidate_id,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result


# --- individual stages -------------------------------------------------


def _stage_wf00(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    result = ingest_master_resume(repo_root, candidate_id, context, write=not payload.get("dry_run"))
    return {
        "ok": True,
        "extraction_mode": result.extraction_mode,
        "fields_updated": result.fields_updated,
        "skills_found": result.skills_found,
        "rejected_skills": result.rejected_skills,
        "model_usage": result.model_usage,
    }


def _stage_wf01(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    path = persist_runtime_context(repo_root, context)
    return {
        "ok": True,
        "run_id": context["run_id"],
        "ai_provider": context["ai_provider"],
        "ai_model": context["ai_model"],
        "portals": context["portal_list"],
        "run_context_path": str(path),
    }


def _stage_wf02(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    input_dir = Path(payload.get("input_dir") or (repo_root / "data" / "job_feeds"))
    if not input_dir.is_absolute():
        input_dir = repo_root / input_dir
    if not input_dir.exists():
        raise StageError(f"job feed directory not found: {input_dir}")

    result = run_job_search(repo_root, context, input_dir=input_dir)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    eligible = json.loads(result.eligible_jobs_path.read_text(encoding="utf-8"))

    # Promote WF02 output into the spec's browsable folder layout.
    profile_name = _profile_name(context)
    targets: List[str] = []
    for job in eligible:
        target = resolve_target(
            repo_root=repo_root,
            candidate_id=candidate_id,
            profile_name=profile_name,
            company=str(job.get("company", "unknown")),
            role=str(job.get("role_title", "unknown")),
        )
        staged = result.output_dir / "job_artifacts"
        for name in ("JD.txt", "metadata.json"):
            for candidate_dir in staged.glob("*"):
                source = candidate_dir / name
                if source.exists() and str(job.get("company", "")).lower().replace(" ", "_") in candidate_dir.name:
                    (target.directory / name).write_bytes(source.read_bytes())
        append_log(target.directory, "WF02", "persist_job_target", "OK", job.get("decision", ""))
        targets.append(str(target.directory))

    return {
        "ok": True,
        "total_jobs": summary["total_jobs"],
        "apply": summary["apply_count"],
        "review": summary["review_count"],
        "skip": summary["skip_count"],
        "scoring_mode": summary.get("scoring_mode"),
        "model_usage": summary.get("model_usage", {}),
        "targets": targets,
    }


def _stage_wf03(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    master = _master_resume(repo_root, context)
    generated: List[Dict[str, Any]] = []

    for directory in _targets_for(repo_root, candidate_id, payload):
        if master is not None:
            copy_master_resume(directory, master)
        result = generate_resume_bundle(repo_root, context, directory)
        append_log(directory, "WF03", "generate_resume", "OK", f"mode={result.generation_mode}")
        generated.append(
            {
                "directory": str(directory),
                "mode": result.generation_mode,
                "pdf": str(result.resume_pdf_path),
                "model_usage": result.model_usage,
            }
        )
    return {"ok": True, "generated": len(generated), "resumes": generated}


def _stage_wf04(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    generated: List[Dict[str, Any]] = []
    for directory in _targets_for(repo_root, candidate_id, payload):
        if not (directory / "resume.json").exists():
            continue
        result = generate_cover_letter_bundle(repo_root, context, directory)
        append_log(directory, "WF04", "generate_cover_letter", "OK", f"mode={result.generation_mode}")
        generated.append({"directory": str(directory), "mode": result.generation_mode,
                          "pdf": str(result.cover_letter_pdf_path), "model_usage": result.model_usage})
    return {"ok": True, "generated": len(generated), "cover_letters": generated}


def _stage_wf05(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    executed: List[Dict[str, Any]] = []
    for directory in _targets_for(repo_root, candidate_id, payload):
        if not (directory / "CoverLetter.pdf").exists():
            continue
        result = execute_application(repo_root, context, directory)
        append_log(directory, "WF05", "execute_application", result.status)
        executed.append({"directory": str(directory), "status": result.status})
    return {"ok": True, "executed": len(executed), "applications": executed}


def _stage_wf06(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    sent: List[Dict[str, Any]] = []
    for directory in _targets_for(repo_root, candidate_id, payload):
        if not (directory / "Application.json").exists():
            continue
        dispatch_notifications(repo_root, context, directory)
        append_log(directory, "WF06", "dispatch_notifications", "OK")
        sent.append({"directory": str(directory)})
    return {"ok": True, "notified": len(sent)}


def _stage_wf07(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    only_applied = payload.get("only_applied", True)
    packs: List[Dict[str, Any]] = []

    for directory in _targets_for(repo_root, candidate_id, payload):
        application = directory / "Application.json"
        if only_applied and application.exists():
            status = json.loads(application.read_text(encoding="utf-8")).get("status", "")
            if status != "Applied":
                continue
        if not (directory / "resume.json").exists():
            continue
        result = generate_interview_prep(repo_root, context, directory)
        append_log(directory, "WF07", "generate_interview_prep", "OK")
        packs.append({"directory": str(directory), "mode": result.generation_mode})
    return {"ok": True, "packs": len(packs), "interview_packs": packs}


def _stage_wf08(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _context(repo_root, candidate_id)
    result = build_dashboard(repo_root, context)
    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    index = build_index(repo_root, candidate_id)
    index_path = repo_root / "output" / candidate_id / "dashboard" / "artifact_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "jobs_found": summary.get("jobs_found", 0),
        "applied": summary.get("applied", 0),
        "tokens": summary.get("token_usage", 0),
        "cost_usd": summary.get("estimated_cost", 0),
        "targets": index["total_targets"],
        "interview_ready": index["interview_ready_count"],
    }


# --- helpers -----------------------------------------------------------


def _targets_for(repo_root: Path, candidate_id: str, payload: Dict[str, Any]) -> List[Path]:
    """Job folders a stage should act on: an explicit list, or all of them."""
    explicit = payload.get("targets")
    if isinstance(explicit, list) and explicit:
        dirs = [Path(item) for item in explicit]
    else:
        dirs = _artifact_dirs(repo_root, candidate_id)

    profiles_root = (repo_root / "Profiles").resolve()
    safe: List[Path] = []
    for directory in dirs:
        resolved = directory.resolve()
        try:
            resolved.relative_to(profiles_root)
        except ValueError:
            continue  # Never act outside the artifact tree.
        if resolved.is_dir():
            safe.append(resolved)
    return safe


def _master_resume(repo_root: Path, context: Dict[str, Any]) -> Path | None:
    folder = Path(str((context.get("paths") or {}).get("resume_folder", "")))
    if not folder.exists():
        return None
    return find_master_resume(folder)


_HANDLERS: Dict[str, Callable[[Path, str, Dict[str, Any]], Dict[str, Any]]] = {
    "wf00": _stage_wf00,
    "wf01": _stage_wf01,
    "wf02": _stage_wf02,
    "wf03": _stage_wf03,
    "wf04": _stage_wf04,
    "wf05": _stage_wf05,
    "wf06": _stage_wf06,
    "wf07": _stage_wf07,
    "wf08": _stage_wf08,
}
