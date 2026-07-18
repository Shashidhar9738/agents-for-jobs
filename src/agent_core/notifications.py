from __future__ import annotations

import json
import logging
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)


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
    sent_result = _attempt_send(name, config, message)
    return sent_result


def _attempt_send(name: str, config: Dict[str, Any], message: str) -> Dict[str, Any]:
    try:
        if name == "email":
            return _send_email(config, message)
        if name == "whatsapp":
            return _send_whatsapp(config, message)
    except Exception as exc:
        log.warning("Notification send failed for %s: %s", name, exc)
        return {"channel": name, "status": "error", "reason": str(exc), "message": message}
    return {"channel": name, "status": "queued", "message": message}


def _send_email(config: Dict[str, Any], message: str) -> Dict[str, Any]:
    to_addr = str(config.get("to", "")).strip()
    from_env = str(config.get("from_env", "NOTIFICATION_EMAIL"))
    smtp_pass_env = str(config.get("smtp_pass_env", "NOTIFICATION_EMAIL_PASSWORD"))
    from_addr = os.getenv(from_env, "").strip()
    smtp_password = os.getenv(smtp_pass_env, "").strip()
    if not from_addr or not smtp_password or not to_addr:
        return {
            "channel": "email",
            "status": "skipped",
            "reason": "Missing from address, SMTP password, or destination",
            "message": message,
        }
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[AI Job Agent] {message[:80]}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(message, "plain"))
    provider = str(config.get("provider", "gmail")).lower()
    smtp_host = "smtp.gmail.com" if provider == "gmail" else str(config.get("smtp_host", "smtp.gmail.com"))
    smtp_port = int(config.get("smtp_port", 587))
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(from_addr, smtp_password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
    return {"channel": "email", "status": "sent", "to": to_addr, "message": message}


def _send_whatsapp(config: Dict[str, Any], message: str) -> Dict[str, Any]:
    to_number = str(config.get("to", "")).strip()
    account_sid = os.getenv(str(config.get("account_sid_env", "TWILIO_ACCOUNT_SID")), "").strip()
    auth_token = os.getenv(str(config.get("auth_token_env", "TWILIO_AUTH_TOKEN")), "").strip()
    from_number = str(config.get("from", "whatsapp:+14155238886")).strip()
    if not account_sid or not auth_token or not to_number:
        return {
            "channel": "whatsapp",
            "status": "skipped",
            "reason": "Missing Twilio credentials or destination number",
            "message": message,
        }
    try:
        from twilio.rest import Client  # type: ignore[import-untyped]
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message,
            from_=f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number,
            to=f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
        )
        return {"channel": "whatsapp", "status": "sent", "to": to_number, "message": message}
    except ImportError:
        return {"channel": "whatsapp", "status": "skipped", "reason": "twilio package not installed", "message": message}


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise NotificationDispatchError(f"Field '{field_name}' must be an object")
    return value