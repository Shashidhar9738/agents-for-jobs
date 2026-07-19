from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.agent_core.ai_client import AIClient, AIClientError
from src.agent_core.prompt_loader import PromptLoadError, collect_prompt_versions, load_prompt

log = logging.getLogger(__name__)


def _fall_back(reason: str) -> None:
    """Say why AI extraction was abandoned.

    Regex recovers little more than an email address, so a run that quietly
    degrades produces a profile with no skills - and then WF02 scores every job
    against nothing and finds no matches. The cause has to reach the operator.
    """
    log.warning(
        "WF00 could not use the model (%s) - falling back to regex extraction, "
        "which does not recover skills or job titles.",
        reason,
    )


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


MASTER_RESUME_SUFFIXES = (".pdf", ".docx", ".txt", ".md")


def find_master_resume(resume_folder: Path) -> Path | None:
    """Locate the candidate's master resume.

    Shared by WF00, WF03 and the stage runner so the three cannot disagree
    about which file counts as the master.
    """
    for suffix in MASTER_RESUME_SUFFIXES:
        candidate = resume_folder / f"resume_master{suffix}"
        if candidate.exists():
            return candidate

    # Exact names are preferred, but a suffixed copy (resume_master1.pdf,
    # resume_master_v2.pdf) is a normal way to keep a newer draft around and
    # should not stop the run. Newest wins.
    if not resume_folder.exists():
        return None
    suffixed = [
        path
        for path in resume_folder.glob("resume_master*")
        if path.is_file() and path.suffix.lower() in MASTER_RESUME_SUFFIXES
    ]
    if not suffixed:
        return None
    return max(suffixed, key=lambda path: path.stat().st_mtime)


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
    except AIClientError as exc:
        _fall_back(f"client unavailable: {exc}")
        return _regex_extract(resume_text), "regex", {}, {}

    if not client.available:
        _fall_back("no provider credential configured")
        return _regex_extract(resume_text), "regex", {}, {}

    try:
        system_prompt = load_prompt(repo_root, "system")
    except PromptLoadError as exc:
        _fall_back(f"prompt missing: {exc}")
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
    except AIClientError as exc:
        _fall_back(str(exc))
        return _regex_extract(resume_text), "regex", {}, {}

    if not response.data:
        _fall_back("model reply was empty or not valid JSON")
        return _regex_extract(resume_text), "regex", {}, {}

    return (
        response.data,
        "ai",
        collect_prompt_versions(system_prompt),
        client.usage.as_metadata(),
    )


_SKILLS_HEADINGS = (
    "TECHNICAL SKILLS",
    "TECHNICAL EXPERTISE",
    "SKILLS & TOOLS",
    "SKILLS",
    "CORE COMPETENCIES",
    "TECHNOLOGIES",
)

# A run of capitals on its own line is the next section starting.
_SECTION_BREAK = re.compile(r"^[A-Z][A-Z &/'-]{3,}$")


def _extract_skills(resume_text: str) -> List[str]:
    """Pull skills out of a resume's skills section without a model.

    PDF extraction wraps lines mid-phrase, so the section is rejoined before
    splitting. Entries are usually written as 'Category: item, item', and the
    category label itself is not a skill. Anything found here is still checked
    against the resume text by _merge_profile, so over-collecting is safe -
    under-collecting is not, because an empty skill list makes WF02 match
    nothing.
    """
    upper = resume_text.upper()
    start = -1
    for heading in _SKILLS_HEADINGS:
        found = upper.find(heading)
        if found != -1:
            start = found + len(heading)
            break
    if start == -1:
        return []

    lines = resume_text[start:].splitlines()
    body: List[str] = []
    for line in lines[1:] if lines and not lines[0].strip() else lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_BREAK.match(stripped) and stripped.upper() not in _SKILLS_HEADINGS:
            break
        body.append(stripped)
    if not body:
        return []

    skills: List[str] = []
    for chunk in " ".join(body).split(","):
        item = chunk.strip()
        # Drop a leading 'Category:' label, keeping the value after it.
        if ":" in item:
            item = item.split(":", 1)[1].strip()
        # Trailing prose after an em/en dash is a description, not a skill.
        item = re.split(r"[–—-]\s", item, maxsplit=1)[0].strip()
        item = item.strip(" .;|")
        if not item or len(item) > 40:
            continue
        if item.lower() in {"and", "etc", "others"}:
            continue
        if item not in skills:
            skills.append(item)
    return skills


def _regex_extract(resume_text: str) -> Dict[str, Any]:
    """Credential-free fallback: pull the fields that have reliable shapes."""
    extracted: Dict[str, Any] = {}

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume_text)
    if email:
        extracted["email"] = email.group(0)

    phone = re.search(r"(?:\+\d{1,3}[\s-]?)?\d{10}\b", resume_text)
    if phone:
        extracted["phone"] = phone.group(0).strip()

    # Accept decimals: '4.5+ years' should not be read as 5.
    years = re.search(
        r"(\d{1,2}(?:\.\d)?)\+?\s*years?\s+(?:of\s+)?experience", resume_text, re.IGNORECASE
    )
    if years:
        value = float(years.group(1))
        extracted["experience_years"] = int(value) if value.is_integer() else value

    skills = _extract_skills(resume_text)
    if skills:
        extracted["skills"] = skills

    return extracted


def _merge_profile(
    existing: Dict[str, Any],
    extracted: Dict[str, Any],
    resume_text: str,
) -> tuple[Dict[str, Any], List[str], List[str], List[str]]:
    """Merge extracted facts into the profile, dropping anything not in the resume."""
    merged = dict(existing)
    updated: List[str] = []
    # PDF extraction wraps phrases across lines, so 'Selenium WebDriver' can
    # arrive as 'Selenium\nWebDriver'. Collapse whitespace before the literal
    # check, or genuine resume skills get rejected as fabrications.
    lowered_resume = re.sub(r"\s+", " ", resume_text).lower()

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
