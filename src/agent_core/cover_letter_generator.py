from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


class CoverLetterGenerationError(ValueError):
    """Raised when WF04 inputs are incomplete or invalid."""


@dataclass
class CoverLetterGenerationResult:
    output_dir: Path
    cover_letter_text_path: Path
    cover_letter_docx_path: Path
    cover_letter_pdf_path: Path


def generate_cover_letter_bundle(
    repo_root: Path,
    run_context: Dict[str, Any],
    job_artifact_dir: Path,
    output_dir: Path | None = None,
) -> CoverLetterGenerationResult:
    candidate_id = _require_text(run_context.get("candidate_id"), "candidate_id")
    candidate_profile = _require_dict(run_context.get("candidate_profile"), "candidate_profile")

    prompt_path = repo_root / "prompts" / "cover_letter.md"
    if not prompt_path.exists():
        raise CoverLetterGenerationError(f"Missing prompt file: {prompt_path}")

    jd_path = job_artifact_dir / "JD.txt"
    metadata_path = job_artifact_dir / "metadata.json"
    resume_json_path = job_artifact_dir / "resume.json"
    if not jd_path.exists() or not metadata_path.exists() or not resume_json_path.exists():
        raise CoverLetterGenerationError(
            f"WF04 requires JD.txt, metadata.json, and resume.json in {job_artifact_dir}"
        )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    resume_json = json.loads(resume_json_path.read_text(encoding="utf-8"))
    jd_text = jd_path.read_text(encoding="utf-8").strip()
    cover_letter_text = _build_cover_letter(candidate_profile, metadata, resume_json, jd_text)
    _validate_cover_letter(cover_letter_text, candidate_profile)

    destination_dir = output_dir or job_artifact_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    text_path = destination_dir / "CoverLetter.txt"
    docx_path = destination_dir / "CoverLetter.docx"
    pdf_path = destination_dir / "CoverLetter.pdf"

    text_path.write_text(cover_letter_text, encoding="utf-8")
    _write_docx(docx_path, cover_letter_text, metadata)
    _write_pdf(pdf_path, cover_letter_text, metadata)

    return CoverLetterGenerationResult(
        output_dir=destination_dir,
        cover_letter_text_path=text_path,
        cover_letter_docx_path=docx_path,
        cover_letter_pdf_path=pdf_path,
    )


def _build_cover_letter(
    candidate_profile: Dict[str, Any],
    metadata: Dict[str, Any],
    resume_json: Dict[str, Any],
    jd_text: str,
) -> str:
    candidate_name = str(candidate_profile.get("name", "Candidate")).strip() or "Candidate"
    current_title = str(candidate_profile.get("current_title", "Professional")).strip() or "Professional"
    company = str(metadata.get("company", "your team")).strip() or "your team"
    role = str(metadata.get("role_title", "the role")).strip() or "the role"
    location = str(metadata.get("location", "")).strip()
    matched_keywords = resume_json.get("match_keywords_found", [])[:4]
    skills = resume_json.get("updated_skills_order", [])[:5]
    summary = str(resume_json.get("updated_professional_summary", "")).strip()
    bullet = ", ".join(skills or matched_keywords or ["relevant testing skills"])
    keyword_phrase = ", ".join(matched_keywords) if matched_keywords else bullet
    location_sentence = ""
    if location:
        location_sentence = f" I am also aligned with the role's location and work-mode expectations in {location}."

    paragraphs = [
        (
            f"Dear Hiring Team,\n\nI am writing to express interest in the {role} opportunity at {company}. "
            f"The role stands out because it emphasizes {keyword_phrase}, which matches the verified experience I have built as a {current_title}."
        ),
        (
            f"Across my background, I have focused on {bullet}. {summary} "
            f"That evidence-backed alignment is the main reason I believe I can contribute effectively in this position."
        ),
        (
            f"What makes this opportunity especially relevant is the overlap between the job description and the work I can support today: {keyword_phrase}."
            f" I would bring a practical, quality-focused approach grounded in the experience already reflected in my resume.{location_sentence}"
        ),
        (
            f"Thank you for your time and consideration. I would welcome the opportunity to discuss how my background can support {company}'s goals in the {role} position.\n\n"
            f"Sincerely,\n{candidate_name}"
        ),
    ]

    text = "\n\n".join(paragraphs)
    return _fit_word_window(text, 220, 320, candidate_profile, metadata, resume_json)


def _fit_word_window(
    text: str,
    min_words: int,
    max_words: int,
    candidate_profile: Dict[str, Any],
    metadata: Dict[str, Any],
    resume_json: Dict[str, Any],
) -> str:
    words = text.split()
    if len(words) > max_words:
        return " ".join(words[:max_words])
    if len(words) >= min_words:
        return text

    additions: List[str] = []
    remaining_gaps = resume_json.get("remaining_gaps", [])
    if remaining_gaps:
        additions.append(
            "I am careful to present my fit honestly, including where the role asks for depth that would need to be demonstrated in discussion rather than overstated in writing."
        )
    if candidate_profile.get("experience_years"):
        additions.append(
            f"My {int(candidate_profile.get('experience_years', 0) or 0)} years of experience have reinforced a disciplined approach to delivery, collaboration, and quality ownership."
        )
    if metadata.get("source"):
        additions.append(
            f"I appreciate the chance to be considered through {metadata.get('source')} and would be glad to provide any additional details needed for review."
        )

    enriched = text
    for sentence in additions:
        if len(enriched.split()) >= min_words:
            break
        enriched = enriched.replace("\n\nThank you", f" {sentence}\n\nThank you")
    return enriched


def _validate_cover_letter(text: str, candidate_profile: Dict[str, Any]) -> None:
    word_count = len(text.split())
    if word_count < 220 or word_count > 320:
        raise CoverLetterGenerationError("Generated cover letter does not satisfy the 220-320 word constraint")
    if "%" in text:
        raise CoverLetterGenerationError("Generated cover letter contains unsupported numeric claims")
    candidate_name = str(candidate_profile.get("name", "")).strip()
    if candidate_name and candidate_name not in text:
        raise CoverLetterGenerationError("Generated cover letter is missing the candidate name signature")


def _write_docx(output_path: Path, text: str, metadata: Dict[str, Any]) -> None:
    document = Document()
    document.add_heading(f"Cover Letter - {metadata.get('role_title', 'Role')}", level=1)
    for paragraph in text.split("\n\n"):
        document.add_paragraph(paragraph.strip())
    document.save(output_path)


def _write_pdf(output_path: Path, text: str, metadata: Dict[str, Any]) -> None:
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    top = height - 0.75 * inch
    left = 0.75 * inch
    y = top
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(left, y, f"Cover Letter - {metadata.get('role_title', 'Role')}")
    y -= 20
    pdf.setFont("Helvetica", 10)
    for paragraph in text.split("\n\n"):
        for line in _wrap_text(paragraph, 95):
            if y < 0.75 * inch:
                pdf.showPage()
                y = top
                pdf.setFont("Helvetica", 10)
            pdf.drawString(left, y, line)
            y -= 14
        y -= 8
    pdf.save()


def _wrap_text(text: str, width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverLetterGenerationError(f"Field '{field_name}' must be an object")
    return value


def _require_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CoverLetterGenerationError(f"Missing required field: {field_name}")
    return text