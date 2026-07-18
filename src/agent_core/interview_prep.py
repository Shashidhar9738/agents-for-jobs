from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


class InterviewPrepError(ValueError):
    """Raised when WF07 inputs are incomplete or invalid."""


@dataclass
class InterviewPrepResult:
    answers_md_path: Path
    interview_questions_pdf_path: Path


def generate_interview_prep(
    repo_root: Path,
    run_context: Dict[str, Any],
    job_artifact_dir: Path,
    output_dir: Path | None = None,
) -> InterviewPrepResult:
    candidate_profile = _require_dict(run_context.get("candidate_profile"), "candidate_profile")
    metadata_path = job_artifact_dir / "metadata.json"
    jd_path = job_artifact_dir / "JD.txt"
    resume_json_path = job_artifact_dir / "resume.json"
    if not metadata_path.exists() or not jd_path.exists() or not resume_json_path.exists():
        raise InterviewPrepError(f"WF07 requires metadata.json, JD.txt, and resume.json in {job_artifact_dir}")

    prompt_path = repo_root / "prompts" / "interview.md"
    if not prompt_path.exists():
        prompt_path = repo_root / "prompts" / "interview_prep.md"
    if not prompt_path.exists():
        raise InterviewPrepError("Missing interview prompt file")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    resume_json = json.loads(resume_json_path.read_text(encoding="utf-8"))
    jd_text = jd_path.read_text(encoding="utf-8")
    markdown = _build_markdown(run_context, candidate_profile, metadata, resume_json, jd_text)

    destination_dir = output_dir or job_artifact_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    answers_md_path = destination_dir / "Answers.md"
    interview_questions_pdf_path = destination_dir / "InterviewQuestions.pdf"
    answers_md_path.write_text(markdown, encoding="utf-8")
    _write_pdf(interview_questions_pdf_path, markdown)
    return InterviewPrepResult(
        answers_md_path=answers_md_path,
        interview_questions_pdf_path=interview_questions_pdf_path,
    )


def _build_markdown(
    run_context: Dict[str, Any],
    candidate_profile: Dict[str, Any],
    metadata: Dict[str, Any],
    resume_json: Dict[str, Any],
    jd_text: str,
) -> str:
    keywords = resume_json.get("match_keywords_found", [])[:8]
    skills = resume_json.get("updated_skills_order", [])[:6]
    role = metadata.get("role_title", "")
    company = metadata.get("company", "")
    candidate_id = run_context.get("candidate_id", "")

    questions = [
        f"How has your experience prepared you for the {role} role at {company}?",
        f"Walk through a recent automation effort that relates to {', '.join(skills[:3]) or 'the required toolset'}.",
        f"How do you approach quality risks when a role emphasizes {', '.join(keywords[:3]) or 'core responsibilities'}?",
        "How do you prioritize regression, API, and exploratory coverage under release pressure?",
        "Describe how you collaborate with developers and product stakeholders when a defect blocks release confidence.",
        "What indicators tell you an automation suite is healthy or becoming brittle?",
        "How would you ramp up during the first month in this role?",
        "Which part of your resume is most relevant here and why?",
        "Where would an interviewer probe deeper based on your current profile?",
        "What would you ask this team to understand their test strategy and quality expectations?",
    ]
    pointers = [
        f"Anchor answers in verified experience with {', '.join(skills[:4]) or 'your documented skills'}.",
        "Use STAR structure for behavioral responses.",
        "Do not overstate tools or scale not already backed by your resume.",
        "Be ready to explain tradeoffs, debugging approach, and communication habits.",
    ]
    technical_focus = keywords or skills or ["Role-specific tooling from the JD"]
    behavioral = [
        "Describe a time you handled an urgent quality issue close to release.",
        "Describe a disagreement on quality scope and how you resolved it.",
        "Describe how you improved reliability or clarity in a test process.",
    ]
    deep_dive = [f"Be ready to unpack bullets related to {item}." for item in resume_json.get("rewritten_experience_project_bullets", [])[:4]]
    gaps = resume_json.get("remaining_gaps", [])
    readiness = [
        "30 days: map product flows, tooling, and defect lifecycle.",
        "60 days: own a scoped automation or quality-improvement deliverable.",
        "90 days: contribute measurable regression confidence and release readiness improvements.",
    ]
    ask_interviewer = [
        "How do you measure release quality and test effectiveness?",
        "What are the highest-risk workflows for this role to support first?",
        "How is automation maintained and reviewed across teams?",
    ]

    sections = [
        f"# CandidateId\n{candidate_id}",
        f"# Role Snapshot\n- Company: {company}\n- Role: {role}\n- Key expectations: {', '.join(keywords[:5]) or 'Review the JD for emphasis areas'}",
        "# Top 10 Likely Interview Questions\n" + "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions)),
        "# Suggested Answer Pointers\n" + "\n".join(f"- {item}" for item in pointers),
        "# Technical Focus Areas\n" + "\n".join(f"- {item}" for item in technical_focus),
        "# Behavioral Questions (STAR-ready)\n" + "\n".join(f"- {item}" for item in behavioral),
        "# Resume Deep-Dive Questions\n" + "\n".join(f"- {item}" for item in deep_dive),
        "# Gaps and Risk Areas\n" + "\n".join(f"- {item}" for item in gaps),
        "# 30-60-90 Day Readiness Plan\n" + "\n".join(f"- {item}" for item in readiness),
        "# Questions to Ask the Interviewer\n" + "\n".join(f"- {item}" for item in ask_interviewer),
    ]
    return "\n\n".join(sections)


def _write_pdf(output_path: Path, markdown: str) -> None:
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 0.75 * inch
    top = height - 0.75 * inch
    y = top
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            y -= 8
            continue
        if y < 0.75 * inch:
            pdf.showPage()
            y = top
        if line.startswith("# "):
            pdf.setFont("Helvetica-Bold", 12)
            text = line[2:]
        else:
            pdf.setFont("Helvetica", 10)
            text = line
        for segment in _wrap_text(text, 95):
            if y < 0.75 * inch:
                pdf.showPage()
                y = top
                pdf.setFont("Helvetica", 10)
            pdf.drawString(left, y, segment)
            y -= 14
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
        raise InterviewPrepError(f"Field '{field_name}' must be an object")
    return value