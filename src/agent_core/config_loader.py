from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


class ConfigValidationError(ValueError):
    """Raised when configuration validation fails."""


def _read_json(file_path: Path) -> Dict[str, Any]:
    if not file_path.exists():
        raise ConfigValidationError(f"Missing config file: {file_path}")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid JSON in {file_path}: {exc}") from exc


def _require_keys(obj: Dict[str, Any], keys: List[str], context: str) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        raise ConfigValidationError(f"{context} missing required keys: {', '.join(missing)}")


def _validate_workspace(workspace: Dict[str, Any]) -> None:
    _require_keys(workspace, ["version", "active_candidate", "candidates"], "workspace config")
    if not isinstance(workspace["candidates"], dict) or not workspace["candidates"]:
        raise ConfigValidationError("workspace config requires non-empty 'candidates' map")
    active_candidate = workspace["active_candidate"]
    if active_candidate not in workspace["candidates"]:
        raise ConfigValidationError(
            f"active_candidate '{active_candidate}' not found in workspace candidates"
        )



def _validate_candidate_profile(profile: Dict[str, Any], candidate_id: str) -> None:
    _require_keys(
        profile,
        ["name", "experience_years", "skills", "locations", "links"],
        f"candidate profile '{candidate_id}'",
    )
    if not isinstance(profile["skills"], list):
        raise ConfigValidationError(f"candidate '{candidate_id}' profile.skills must be an array")



def _validate_candidate_preferences(preferences: Dict[str, Any], candidate_id: str) -> None:
    _require_keys(
        preferences,
        ["minimum_match", "target_roles", "locations"],
        f"candidate preferences '{candidate_id}'",
    )



def _validate_core_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    for name in ["ai-models", "portals", "notifications", "profiles"]:
        if name not in configs:
            raise ConfigValidationError(f"missing core config '{name}'")



def _resolve_repo_path(repo_root: Path, relative_path: str) -> Path:
    return (repo_root / relative_path).resolve()



def build_runtime_context(repo_root: Path, candidate_override: str | None = None) -> Dict[str, Any]:
    config_dir = repo_root / "config"
    workspace_path = config_dir / "workspace.json"

    workspace_cfg = _read_json(workspace_path)
    _validate_workspace(workspace_cfg)

    candidate_id = candidate_override or workspace_cfg["active_candidate"]
    if candidate_id not in workspace_cfg["candidates"]:
        raise ConfigValidationError(f"candidate '{candidate_id}' not found in workspace config")

    candidate_cfg = workspace_cfg["candidates"][candidate_id]
    _require_keys(
        candidate_cfg,
        ["display_name", "profile_path", "preferences_path", "resume_folder", "tracker_csv"],
        f"candidate mapping '{candidate_id}'",
    )

    profile_path = _resolve_repo_path(repo_root, candidate_cfg["profile_path"])
    preferences_path = _resolve_repo_path(repo_root, candidate_cfg["preferences_path"])

    profile_cfg = _read_json(profile_path)
    preferences_cfg = _read_json(preferences_path)

    _validate_candidate_profile(profile_cfg, candidate_id)
    _validate_candidate_preferences(preferences_cfg, candidate_id)

    core_configs: Dict[str, Dict[str, Any]] = {}
    for base_name in ["ai-models", "portals", "notifications", "profiles"]:
        core_configs[base_name] = _read_json(config_dir / f"{base_name}.json")

    _validate_core_configs(core_configs)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    resume_folder = _resolve_repo_path(repo_root, candidate_cfg["resume_folder"])
    tracker_csv = _resolve_repo_path(repo_root, candidate_cfg["tracker_csv"])

    context = {
        "run_id": run_id,
        "started_at": started_at,
        "candidate_id": candidate_id,
        "candidate_display_name": candidate_cfg["display_name"],
        "candidate_profile": profile_cfg,
        "candidate_preferences": preferences_cfg,
        "ai_models": core_configs["ai-models"],
        "portals": core_configs["portals"],
        "notifications": core_configs["notifications"],
        "profiles": core_configs["profiles"],
        "paths": {
            "repo_root": str(repo_root.resolve()),
            "profile_path": str(profile_path),
            "preferences_path": str(preferences_path),
            "resume_folder": str(resume_folder),
            "tracker_csv": str(tracker_csv),
            "prompts_dir": str((repo_root / "prompts").resolve()),
            "logs_dir": str((repo_root / "logs").resolve()),
        },
    }

    return context



def validate_all_configs(repo_root: Path) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    try:
        workspace = _read_json(repo_root / "config" / "workspace.json")
        _validate_workspace(workspace)
    except ConfigValidationError as exc:
        errors.append(str(exc))
        return False, errors

    for candidate_id in workspace["candidates"].keys():
        try:
            build_runtime_context(repo_root, candidate_override=candidate_id)
        except ConfigValidationError as exc:
            errors.append(str(exc))

    return len(errors) == 0, errors
