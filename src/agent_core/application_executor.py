from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont


class ApplicationExecutionError(ValueError):
    """Raised when WF05 execution inputs are invalid."""


@dataclass
class ApplicationExecutionResult:
    application_json_path: Path
    screenshot_path: Path
    tracker_csv_path: Path
    status: str


def execute_application(
    repo_root: Path,
    run_context: Dict[str, Any],
    job_artifact_dir: Path,
    output_dir: Path | None = None,
) -> ApplicationExecutionResult:
    candidate_profile = _require_dict(run_context.get("candidate_profile"), "candidate_profile")
    candidate_preferences = _require_dict(run_context.get("candidate_preferences"), "candidate_preferences")
    paths = _require_dict(run_context.get("paths"), "paths")

    metadata_path = job_artifact_dir / "metadata.json"
    resume_json_path = job_artifact_dir / "resume.json"
    resume_pdf_path = job_artifact_dir / "Resume.pdf"
    cover_letter_pdf_path = job_artifact_dir / "CoverLetter.pdf"
    if not metadata_path.exists() or not resume_json_path.exists() or not resume_pdf_path.exists() or not cover_letter_pdf_path.exists():
        raise ApplicationExecutionError(
            f"WF05 requires metadata.json, resume.json, Resume.pdf, and CoverLetter.pdf in {job_artifact_dir}"
        )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    resume_json = json.loads(resume_json_path.read_text(encoding="utf-8"))

    destination_dir = output_dir or job_artifact_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    application_json_path = destination_dir / "Application.json"
    screenshot_path = destination_dir / "Screenshot.png"

    status = _resolve_status(candidate_profile, candidate_preferences, metadata)
    application_payload = {
        "candidate_id": run_context.get("candidate_id"),
        "run_id": run_context.get("run_id"),
        "company": metadata.get("company"),
        "role_title": metadata.get("role_title"),
        "location": metadata.get("location"),
        "portal": metadata.get("source"),
        "job_url": metadata.get("job_url"),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "submit_mode": "manual_assist" if status != "Applied" else "configured_auto_apply",
        "match_score": metadata.get("match_score"),
        "reason": metadata.get("reason"),
        "resume_used": str(resume_pdf_path),
        "cover_letter_used": str(cover_letter_pdf_path),
        "answers": _build_application_answers(candidate_profile, resume_json),
        "next_action": _next_action_for_status(status),
    }
    application_json_path.write_text(json.dumps(application_payload, indent=2), encoding="utf-8")
    _write_screenshot_summary(screenshot_path, application_payload)

    tracker_csv_path = Path(str(paths.get("tracker_csv"))).resolve()
    _append_tracker_row(tracker_csv_path, application_payload)

    return ApplicationExecutionResult(
        application_json_path=application_json_path,
        screenshot_path=screenshot_path,
        tracker_csv_path=tracker_csv_path,
        status=status,
    )


def _resolve_status(
    candidate_profile: Dict[str, Any],
    candidate_preferences: Dict[str, Any],
    metadata: Dict[str, Any],
) -> str:
    decision = str(metadata.get("decision", "")).strip()
    if decision == "Review":
        return "Review"
    if not str(candidate_profile.get("email", "")).strip() or not str(candidate_profile.get("phone", "")).strip():
        return "Prepared"
    if not bool(candidate_preferences.get("auto_apply", False)):
        return "Prepared"
    return "Applied"


def _build_application_answers(candidate_profile: Dict[str, Any], resume_json: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": candidate_profile.get("name", ""),
        "email": candidate_profile.get("email", ""),
        "phone": candidate_profile.get("phone", ""),
        "experience_years": candidate_profile.get("experience_years", 0),
        "current_title": candidate_profile.get("current_title", ""),
        "skills": resume_json.get("updated_skills_order", []),
        "links": candidate_profile.get("links", {}),
        "locations": candidate_profile.get("locations", []),
    }


def _next_action_for_status(status: str) -> str:
    if status == "Applied":
        return "Send notifications and generate interview preparation"
    if status == "Prepared":
        return "Open portal manually, upload generated documents, and submit"
    return "Review candidate data or job requirements before proceeding"


def _write_screenshot_summary(output_path: Path, application_payload: Dict[str, Any]) -> None:
    image = Image.new("RGB", (1280, 720), color=(245, 247, 250))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    title_font = font
    y = 40
    draw.text((40, y), "Application Execution Summary", fill=(20, 20, 20), font=title_font)
    y += 40
    lines = [
        f"Candidate: {application_payload.get('candidate_id', '')}",
        f"Company: {application_payload.get('company', '')}",
        f"Role: {application_payload.get('role_title', '')}",
        f"Portal: {application_payload.get('portal', '')}",
        f"Status: {application_payload.get('status', '')}",
        f"Next Action: {application_payload.get('next_action', '')}",
        f"URL: {application_payload.get('job_url', '')}",
    ]
    for line in lines:
        draw.text((40, y), line, fill=(45, 45, 45), font=font)
        y += 28
    image.save(output_path)


def _append_tracker_row(tracker_csv_path: Path, application_payload: Dict[str, Any]) -> None:
    tracker_csv_path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["Date", "Company", "Role", "Location", "MatchScore", "Status", "Link"]
    row = {
        "Date": application_payload.get("submitted_at", ""),
        "Company": application_payload.get("company", ""),
        "Role": application_payload.get("role_title", ""),
        "Location": application_payload.get("location", ""),
        "MatchScore": application_payload.get("match_score", ""),
        "Status": application_payload.get("status", ""),
        "Link": application_payload.get("job_url", ""),
    }
    file_exists = tracker_csv_path.exists()
    with tracker_csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        if not file_exists or tracker_csv_path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ApplicationExecutionError(f"Field '{field_name}' must be an object")
    return value