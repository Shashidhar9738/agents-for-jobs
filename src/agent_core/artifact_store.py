from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Spec section 5: the exact artifact set every job target folder must contain.
# Order is presentation order in the dashboard, not creation order.
REQUIRED_ARTIFACTS: List[str] = [
    "JD.txt",
    "metadata.json",
    "Resume.pdf",
    "Resume.docx",
    "resume.json",
    "CoverLetter.pdf",
    "CoverLetter.docx",
    "InterviewQuestions.pdf",
    "Answers.md",
    "Application.json",
    "Screenshot.png",
    "Logs.txt",
]

# Not in the spec's required list, but the candidate's immutable source resume is
# copied alongside so a reviewer can diff tailored output against the original.
MASTER_RESUME_NAME = "MasterResume"

_ARTIFACT_KIND: Dict[str, str] = {
    "JD.txt": "source",
    "metadata.json": "data",
    "Resume.pdf": "resume",
    "Resume.docx": "resume",
    "resume.json": "data",
    "CoverLetter.pdf": "cover_letter",
    "CoverLetter.docx": "cover_letter",
    "InterviewQuestions.pdf": "interview",
    "Answers.md": "interview",
    "Application.json": "data",
    "Screenshot.png": "evidence",
    "Logs.txt": "log",
}


class ArtifactStoreError(ValueError):
    """Raised when an artifact target cannot be resolved or written."""


@dataclass
class ArtifactTarget:
    directory: Path
    candidate_id: str
    profile_name: str
    company: str
    role: str
    is_versioned_rerun: bool


def slugify_segment(value: str) -> str:
    """Normalize one path segment while keeping it human-readable.

    Company and role names become folder names a person will browse, so spaces
    become underscores rather than being stripped, and case is preserved.
    """
    cleaned = "".join(
        character if (character.isalnum() or character in {" ", "-", "_", "."}) else " "
        for character in str(value)
    )
    collapsed = "_".join(part for part in cleaned.split() if part)
    return collapsed.strip("._-") or "unknown"


def resolve_target(
    repo_root: Path,
    candidate_id: str,
    profile_name: str,
    company: str,
    role: str,
    create: bool = True,
) -> ArtifactTarget:
    """Resolve the spec section 5 folder for one job target.

    A rerun against an existing, already-populated target never overwrites: it
    gets a sibling folder with a UTC timestamp suffix.
    """
    if not str(candidate_id).strip():
        raise ArtifactStoreError("candidate_id is required to resolve an artifact target")

    base = (
        repo_root
        / "Profiles"
        / slugify_segment(candidate_id)
        / slugify_segment(profile_name or "default")
        / slugify_segment(company)
    )
    role_segment = slugify_segment(role)
    target = base / role_segment

    is_rerun = False
    if target.exists() and any(target.iterdir()):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = base / f"{role_segment}__{stamp}"
        is_rerun = True

    if create:
        target.mkdir(parents=True, exist_ok=True)

    return ArtifactTarget(
        directory=target,
        candidate_id=str(candidate_id),
        profile_name=str(profile_name or "default"),
        company=str(company),
        role=str(role),
        is_versioned_rerun=is_rerun,
    )


def copy_master_resume(target_dir: Path, master_resume_path: Path) -> Path | None:
    """Place a read-only copy of the immutable master resume beside the tailored one."""
    if not master_resume_path.exists():
        return None
    destination = target_dir / f"{MASTER_RESUME_NAME}{master_resume_path.suffix}"
    shutil.copy2(master_resume_path, destination)
    return destination


def append_log(target_dir: Path, workflow: str, node: str, status: str, detail: str = "") -> None:
    """Append one audit line to the per-artifact Logs.txt (spec section 12)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"{timestamp}\t{workflow}\t{node}\t{status}\t{detail}".rstrip()
    with (target_dir / "Logs.txt").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def build_manifest(target_dir: Path) -> Dict[str, Any]:
    """Describe one job folder: which required artifacts exist, which are missing."""
    if not target_dir.exists():
        raise ArtifactStoreError(f"artifact directory not found: {target_dir}")

    files: List[Dict[str, Any]] = []
    missing: List[str] = []
    for name in REQUIRED_ARTIFACTS:
        path = target_dir / name
        if path.exists():
            files.append(
                {
                    "name": name,
                    "kind": _ARTIFACT_KIND.get(name, "other"),
                    "size_bytes": path.stat().st_size,
                    "path": str(path),
                }
            )
        else:
            missing.append(name)

    master = next(
        (path for path in target_dir.glob(f"{MASTER_RESUME_NAME}.*") if path.is_file()),
        None,
    )
    if master is not None:
        files.insert(
            0,
            {
                "name": master.name,
                "kind": "master_resume",
                "size_bytes": master.stat().st_size,
                "path": str(master),
            },
        )

    metadata = _read_json_if_present(target_dir / "metadata.json")
    application = _read_json_if_present(target_dir / "Application.json")

    return {
        "directory": str(target_dir),
        "folder_name": target_dir.name,
        "company": metadata.get("company", ""),
        "role": metadata.get("role_title", ""),
        "portal": metadata.get("source", ""),
        "job_url": metadata.get("job_url", ""),
        "match_score": metadata.get("match_score"),
        "decision": metadata.get("decision", ""),
        "status": application.get("status", ""),
        "submitted_at": application.get("submitted_at", ""),
        "model_usage": application.get("model_usage", {}),
        "prompt_versions": application.get("prompt_versions", {}),
        "files": files,
        "missing": missing,
        "is_complete": not missing,
        "interview_ready": (target_dir / "InterviewQuestions.pdf").exists()
        and (target_dir / "Answers.md").exists(),
    }


def build_index(repo_root: Path, candidate_id: str | None = None) -> Dict[str, Any]:
    """Walk Profiles/ and produce the browsable index the dashboard renders."""
    profiles_root = repo_root / "Profiles"
    entries: List[Dict[str, Any]] = []

    if profiles_root.exists():
        candidate_dirs = (
            [profiles_root / slugify_segment(candidate_id)]
            if candidate_id
            else [path for path in profiles_root.iterdir() if path.is_dir()]
        )
        for candidate_dir in candidate_dirs:
            if not candidate_dir.is_dir():
                continue
            for profile_dir in sorted(path for path in candidate_dir.iterdir() if path.is_dir()):
                for company_dir in sorted(path for path in profile_dir.iterdir() if path.is_dir()):
                    for role_dir in sorted(path for path in company_dir.iterdir() if path.is_dir()):
                        manifest = build_manifest(role_dir)
                        manifest["candidate_id"] = candidate_dir.name
                        manifest["profile_name"] = profile_dir.name
                        if not manifest["company"]:
                            manifest["company"] = company_dir.name.replace("_", " ")
                        if not manifest["role"]:
                            manifest["role"] = role_dir.name.split("__")[0].replace("_", " ")
                        entries.append(manifest)

    entries.sort(key=lambda item: (item.get("submitted_at") or "", item.get("company") or ""), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate_id or "all",
        "total_targets": len(entries),
        "interview_ready_count": sum(1 for item in entries if item["interview_ready"]),
        "incomplete_count": sum(1 for item in entries if not item["is_complete"]),
        "targets": entries,
    }


def _read_json_if_present(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
