from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.agent_core.ai_client import AIClient, AIClientError
from src.agent_core.prompt_loader import PromptLoadError, collect_prompt_versions, load_prompt


class ResumeIngestError(ValueError):
    """Raised when the master resume cannot be read or parsed."""


@dataclass
class IngestResult:
    candidate_id: str
    profile_path: Path
    source_resume: Path
    extraction_mode: str
    fields_updated: List[str] = field(default_factory=list)
    skills_found: List[str] = field(default_factory=list)
    rejected_skills: List[str] = field(default_factory=list)
    prompt_versions: Dict[str, Any] = field(default_factory=dict)
    model_usage: Dict[str, Any] = field(default_factory=dict)
    backup_path: Path | None = None


# Fields the resume is allowed to define. Preferences (locations, work modes,
# salary) are candidate choices, not resume facts, so ingestion never touches them.
_RESUME_OWNED_FIELDS = (
    "name",
    "email",
    "phone",
    "current_title",
    "experience_years",
    "skills",
    "education",
    "certifications",
    "work_history",
)


def find_master_resume(resume_folder: Path) -> Path | None:
    for suffix in (".pdf", ".docx", ".txt", ".md"):
        candidate = resume_folder / f"resume_master{suffix}"
        if candidate.exists():
            return candidate
    return None


def extract_resume_text(path: Path) -> str:
    """Read raw text out of the master resume, whatever format it arrived in."""
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        raise ResumeIngestError(f"Unsupported master resume format: {suffix}")

    text = text.strip()
    if not text:
        raise ResumeIngestError(
            f"No text could be extracted from {path.name}. "
            "If this is a scanned or image-only PDF, export a text-based PDF instead."
        )
    return text


def ingest_master_resume(
    repo_root: Path,
    candidate_id: str,
    run_context: Dict[str, Any],
    write: bool = True,
) -> IngestResult:
    """Derive the candidate profile from the master resume.

    The resume is the source of truth: skills and titles come from what the
    candidate actually wrote, not from hand-maintained config that drifts.
    """
    paths = run_context.get("paths")
    if not isinstance(paths, dict):
        raise ResumeIngestError("run context is missing paths")

    resume_folder = Path(str(paths.get("resume_folder", "")))
    source = find_master_resume(resume_folder)
    if source is None:
        raise ResumeIngestError(
            f"No master resume found in {resume_folder}. "
            "Expected resume_master.pdf (or .docx/.txt/.md)."
        )

    resume_text = extract_resume_text(source)
    profile_path = Path(str(run_context.get("candidate_profile_path", "")))
    if not profile_path.exists():
        raise ResumeIngestError(f"Candidate profile not found: {profile_path}")

    existing = json.loads(profile_path.read_text(encoding="utf-8"))

    extracted, mode, prompt_versions, model_usage = _extract_profile_fields(
        repo_root, run_context, resume_text
    )

    merged, updated, kept_skills, rejected_skills = _merge_profile(existing, extracted, resume_text)

    backup_path = None
    if write:
        # The previous profile is archived, never silently replaced.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = profile_path.parent / "previous"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"profile__{stamp}.json"
        backup_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        profile_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    return IngestResult(
        candidate_id=candidate_id,
        profile_path=profile_path,
        source_resume=source,
        extraction_mode=mode,
        fields_updated=updated,
        skills_found=kept_skills,
        rejected_skills=rejected_skills,
        prompt_versions=prompt_versions,
        model_usage=model_usage,
        backup_path=backup_path,
    )


def _extract_profile_fields(
    repo_root: Path,
    run_context: Dict[str, Any],
    resume_text: str,
) -> tuple[Dict[str, Any], str, Dict[str, Any], Dict[str, Any]]:
    """Structure the resume with the model, falling back to regex extraction."""
    try:
        client = AIClient.from_run_context(run_context)
    except AIClientError:
        return _regex_extract(resume_text), "regex", {}, {}

    if not client.available:
        return _regex_extract(resume_text), "regex", {}, {}

    try:
        system_prompt = load_prompt(repo_root, "system")
    except PromptLoadError:
        return _regex_extract(resume_text), "regex", {}, {}

    user_prompt = "\n\n".join(
        [
            "## Task\nExtract structured facts from the resume below. Extract only what is "
            "explicitly written. Never infer, embellish, or add anything not present.",
            "## Resume\n" + resume_text[:12000],
            "## Required Output\n"
            "Return a JSON object with keys: name (string), email (string), phone (string), "
            "current_title (string), experience_years (number), skills (array of strings, the "
            "technologies and tools named in the resume), education (array of strings), "
            "certifications (array of strings), work_history (array of objects with company, "
            "title, duration). Use an empty string or empty array for anything not stated. "
            "Do not guess experience_years - only report it if the resume states it or it is "
            "unambiguous from dates.",
        ]
    )

    try:
        response = client.complete_json(
            system_prompt=system_prompt.text,
            user_prompt=user_prompt,
            purpose="wf00_resume_ingest",
            max_tokens=2048,
        )
    except AIClientError:
        return _regex_extract(resume_text), "regex", {}, {}

    if not response.data:
        return _regex_extract(resume_text), "regex", {}, {}

    return (
        response.data,
        "ai",
        collect_prompt_versions(system_prompt),
        client.usage.as_metadata(),
    )


def _regex_extract(resume_text: str) -> Dict[str, Any]:
    """Credential-free fallback: pull the fields that have reliable shapes."""
    extracted: Dict[str, Any] = {}

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
    if email:
        extracted["email"] = email.group(0)

    phone = re.search(r"(?:\+\d{1,3}[\s-]?)?\d{10}\b", resume_text)
    if phone:
        extracted["phone"] = phone.group(0).strip()

    years = re.search(r"(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience", resume_text, re.IGNORECASE)
    if years:
        extracted["experience_years"] = int(years.group(1))

    return extracted


def _merge_profile(
    existing: Dict[str, Any],
    extracted: Dict[str, Any],
    resume_text: str,
) -> tuple[Dict[str, Any], List[str], List[str], List[str]]:
    """Merge extracted facts into the profile, dropping anything not in the resume."""
    merged = dict(existing)
    updated: List[str] = []
    lowered_resume = resume_text.lower()

    kept_skills: List[str] = []
    rejected_skills: List[str] = []

    for key in _RESUME_OWNED_FIELDS:
        if key not in extracted:
            continue
        value = extracted[key]

        if key == "skills":
            for skill in value if isinstance(value, list) else []:
                text = str(skill).strip()
                if not text:
                    continue
                # Every skill must literally appear in the resume.
                if text.lower() in lowered_resume:
                    if text not in kept_skills:
                        kept_skills.append(text)
                else:
                    rejected_skills.append(text)
            if kept_skills and kept_skills != existing.get("skills"):
                merged["skills"] = kept_skills
                updated.append("skills")
            continue

        if isinstance(value, str):
            text = value.strip()
            if text and text != str(existing.get(key, "")).strip():
                merged[key] = text
                updated.append(key)
            continue

        if isinstance(value, (int, float)) and value:
            if value != existing.get(key):
                merged[key] = value
                updated.append(key)
            continue

        if isinstance(value, list) and value:
            if value != existing.get(key):
                merged[key] = value
                updated.append(key)

    merged["profile_source"] = {
        "derived_from": "master_resume",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return merged, updated, kept_skills, rejected_skills
