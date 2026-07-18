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



def _normalize_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _resolve_ai_selection(ai_models: Dict[str, Any]) -> Tuple[str, str]:
    default_model = ai_models.get("default", "")
    enabled_providers: List[Tuple[str, Dict[str, Any]]] = []
    for provider_name, provider_config in ai_models.items():
        if provider_name == "default" or not isinstance(provider_config, dict):
            continue
        if provider_config.get("enabled"):
            enabled_providers.append((provider_name, provider_config))

    if not enabled_providers:
        raise ConfigValidationError("ai-models config requires at least one enabled provider")

    for provider_name, provider_config in enabled_providers:
        provider_model = provider_config.get("model", "")
        if default_model and provider_model == default_model:
            return provider_name, provider_model

    provider_name, provider_config = enabled_providers[0]
    provider_model = provider_config.get("model") or default_model
    if not provider_model:
        raise ConfigValidationError(
            f"enabled AI provider '{provider_name}' is missing a configured model"
        )
    return provider_name, provider_model


def _resolve_enabled_portals(portals: Dict[str, Any]) -> List[str]:
    enabled_portals = [
        portal_name
        for portal_name, portal_config in portals.items()
        if isinstance(portal_config, dict) and portal_config.get("enabled")
    ]
    if not enabled_portals:
        raise ConfigValidationError("portals config requires at least one enabled portal")
    return enabled_portals


def _resolve_profile_pack(profiles_config: Dict[str, Any], preferences_cfg: Dict[str, Any]) -> Dict[str, Any]:
    available_profiles = profiles_config.get("profiles")
    if not isinstance(available_profiles, list) or not available_profiles:
        raise ConfigValidationError("profiles config requires a non-empty 'profiles' list")

    target_roles = _normalize_string_list(preferences_cfg.get("target_roles"))
    selected_profiles = []
    lowered_roles = [role.lower() for role in target_roles]
    for profile in available_profiles:
        if not isinstance(profile, dict):
            continue
        profile_name = str(profile.get("name", "")).lower()
        profile_id = str(profile.get("id", "")).lower()
        keywords = [keyword.lower() for keyword in _normalize_string_list(profile.get("keywords"))]
        if not lowered_roles:
            selected_profiles.append(profile)
            continue
        if any(role in profile_name or role in profile_id for role in lowered_roles):
            selected_profiles.append(profile)
            continue
        if any(any(role in keyword or keyword in role for keyword in keywords) for role in lowered_roles):
            selected_profiles.append(profile)

    if not selected_profiles:
        selected_profiles = available_profiles

    return {
        "target_roles": target_roles,
        "available_profiles": available_profiles,
        "selected_profiles": selected_profiles,
    }


def _validate_core_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    for name in ["ai-models", "portals", "notifications", "profiles"]:
        if name not in configs:
            raise ConfigValidationError(f"missing core config '{name}'")



def _resolve_repo_path(repo_root: Path, relative_path: str) -> Path:
    return (repo_root / relative_path).resolve()


def _validate_runtime_context_contract(context: Dict[str, Any]) -> None:
    _require_keys(
        context,
        [
            "run_id",
            "started_at",
            "candidate_id",
            "candidate_profile_path",
            "candidate_preferences_path",
            "profile_pack",
            "ai_provider",
            "ai_model",
            "portal_list",
            "paths",
        ],
        "runtime context",
    )



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
    ai_provider, ai_model = _resolve_ai_selection(core_configs["ai-models"])
    portal_list = _resolve_enabled_portals(core_configs["portals"])
    profile_pack = _resolve_profile_pack(core_configs["profiles"], preferences_cfg)

    resume_folder = _resolve_repo_path(repo_root, candidate_cfg["resume_folder"])
    tracker_csv = _resolve_repo_path(repo_root, candidate_cfg["tracker_csv"])

    context = {
        "run_id": run_id,
        "started_at": started_at,
        "candidate_id": candidate_id,
        "candidate_display_name": candidate_cfg["display_name"],
        "candidate_profile_path": str(profile_path),
        "candidate_preferences_path": str(preferences_path),
        "profile_pack": profile_pack,
        "ai_provider": ai_provider,
        "ai_model": ai_model,
        "portal_list": portal_list,
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

    _validate_runtime_context_contract(context)

    return context


def persist_runtime_context(
    repo_root: Path,
    context: Dict[str, Any],
    relative_output_path: str | None = None,
) -> Path:
    logs_dir = (repo_root / "logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    if relative_output_path:
        output_path = (repo_root / relative_output_path).resolve()
    else:
        output_path = logs_dir / f"run_context_{context['candidate_id']}_{context['run_id']}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    return output_path



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
            context = build_runtime_context(repo_root, candidate_override=candidate_id)
            _validate_runtime_context_contract(context)
        except ConfigValidationError as exc:
            errors.append(str(exc))

    return len(errors) == 0, errors
