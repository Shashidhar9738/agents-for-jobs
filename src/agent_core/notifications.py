from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class NotificationDispatchError(ValueError):
    """Raised when WF06 notification inputs are invalid."""


@dataclass
class NotificationDispatchResult:
    log_path: Path
    statuses: List[Dict[str, Any]]


def dispatch_notifications(
    repo_root: Path,
    run_context: Dict[str, Any],
    job_artifact_dir: Path,
    output_dir: Path | None = None,
) -> NotificationDispatchResult:
    notifications_cfg = _require_dict(run_context.get("notifications"), "notifications")
    application_path = job_artifact_dir / "Application.json"
    if not application_path.exists():
        raise NotificationDispatchError(f"WF06 requires Application.json in {job_artifact_dir}")

    prompt_path = repo_root / "prompts" / "notification_message.md"
    if not prompt_path.exists():
        raise NotificationDispatchError(f"Missing prompt file: {prompt_path}")

    application_payload = json.loads(application_path.read_text(encoding="utf-8"))
    message = _build_message(application_payload)
    statuses = []

    email_cfg = notifications_cfg.get("email", {}) if isinstance(notifications_cfg.get("email"), dict) else {}
    whatsapp_cfg = notifications_cfg.get("whatsapp", {}) if isinstance(notifications_cfg.get("whatsapp"), dict) else {}
    statuses.append(_channel_status("email", email_cfg, message))
    statuses.append(_channel_status("whatsapp", whatsapp_cfg, message))

    destination_dir = output_dir or job_artifact_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    log_path = destination_dir / "NotificationLog.json"
    log_path.write_text(json.dumps({"message": message, "channels": statuses}, indent=2), encoding="utf-8")
    return NotificationDispatchResult(log_path=log_path, statuses=statuses)


def _build_message(application_payload: Dict[str, Any]) -> str:
    return (
        f"[{application_payload.get('status', 'UNKNOWN')}] "
        f"{application_payload.get('candidate_id', '')} - {application_payload.get('company', '')} / "
        f"{application_payload.get('role_title', '')} via {application_payload.get('portal', '')} "
        f"(score: {application_payload.get('match_score', 'n/a')})."
    )


def _channel_status(name: str, config: Dict[str, Any], message: str) -> Dict[str, Any]:
    if not config.get("enabled"):
        return {"channel": name, "status": "disabled", "message": message}

    destination = str(config.get("to", "")).strip()
    env_keys = [value for key, value in config.items() if key.endswith("_env") and isinstance(value, str)]
    missing_env = [env_key for env_key in env_keys if not os.getenv(env_key)]
    if not destination:
        return {"channel": name, "status": "skipped", "reason": "Missing destination", "message": message}
    if missing_env:
        return {
            "channel": name,
            "status": "skipped",
            "reason": f"Missing environment variables: {', '.join(missing_env)}",
            "message": message,
        }
    return {
        "channel": name,
        "status": "queued",
        "reason": "Configuration present; delivery adapter can use this payload",
        "message": message,
    }


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise NotificationDispatchError(f"Field '{field_name}' must be an object")
    return value