from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from src.agent_core.ai_client import AIClient, AIClientError
from src.agent_core.prompt_loader import PromptLoadError, collect_prompt_versions, load_prompt


class InterviewPrepError(ValueError):
    """Raised when WF07 inputs are incomplete or invalid."""


@dataclass
class InterviewPrepResult:
    answers_md_path: Path
    interview_questions_pdf_path: Path
    generation_mode: str = "deterministic"
    prompt_versions: Dict[str, Any] = field(default_factory=dict)
    model_usage: Dict[str, Any] = field(default_factory=dict)


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

    generation_mode = "deterministic"
    prompt_versions: Dict[str, Any] = {}
    model_usage: Dict[str, Any] = {}

    ai_outcome = _apply_ai_interview_prep(
        repo_root=repo_root,
        run_context=run_context,
        candidate_profile=candidate_profile,
        metadata=metadata,
        resume_json=resume_json,
        jd_text=jd_text,
    )
    if ai_outcome is not None:
        markdown, generation_mode, prompt_versions, model_usage = ai_outcome

    destination_dir = output_dir or job_artifact_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    answers_md_path = destination_dir / "Answers.md"
    interview_questions_pdf_path = destination_dir / "InterviewQuestions.pdf"
    answers_md_path.write_text(markdown, encoding="utf-8")
    _write_pdf(interview_questions_pdf_path, markdown)
    return InterviewPrepResult(
        answers_md_path=answers_md_path,
        interview_questions_pdf_path=interview_questions_pdf_path,
        generation_mode=generation_mode,
        prompt_versions=prompt_versions,
        model_usage=model_usage,
    )


def _apply_ai_interview_prep(
    repo_root: Path,
    run_context: Dict[str, Any],
    candidate_profile: Dict[str, Any],
    metadata: Dict[str, Any],
    resume_json: Dict[str, Any],
    jd_text: str,
) -> tuple[str, str, Dict[str, Any], Dict[str, Any]] | None:
    """Generate the prep pack with the configured model, or None to keep the baseline."""
    try:
        client = AIClient.from_run_context(run_context)
    except AIClientError:
        return None

    if not client.available:
        return None

    try:
        system_prompt = load_prompt(repo_root, "system")
        interview_prompt = load_prompt(repo_root, "interview")
    except PromptLoadError:
        return None

    user_prompt = "\n\n".join(
        [
            interview_prompt.text,
            "## Job Description\n" + jd_text,
            "## Target Role Metadata\n" + json.dumps(
                {"company": metadata.get("company", ""), "role_title": metadata.get("role_title", "")},
                indent=2,
            ),
            "## Candidate Profile (verified facts)\n" + json.dumps(candidate_profile, indent=2),
            "## Tailored Resume\n" + json.dumps(resume_json, indent=2),
            "## Required Output\n"
            "Return a JSON object with these array-of-string keys: likely_questions (10 items), "
            "answer_pointers, technical_focus, behavioral_questions, resume_deep_dive, "
            "gaps_and_risks, readiness_plan, questions_to_ask. Ground every item in the candidate's "
            "verified experience; never invent tools, employers, metrics, or scale.",
        ]
    )

    try:
        response = client.complete_json(
            system_prompt=system_prompt.text,
            user_prompt=user_prompt,
            purpose="wf07_interview_prep",
        )
    except AIClientError:
        return None

    if not response.data:
        return None

    markdown = _render_ai_markdown(run_context, metadata, response.data)
    if markdown is None:
        return None

    source_text = " ".join([json.dumps(candidate_profile), json.dumps(resume_json), jd_text])
    source_numbers = set(re.findall(r"\d+", source_text))
    # The 30-60-90 framing is a standard planning horizon, not a claim about the
    # candidate, so those figures are allowed through.
    allowed_numbers = source_numbers | {"30", "60", "90", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
    if any(number not in allowed_numbers for number in re.findall(r"\d+", markdown)):
        return None

    prompt_versions = collect_prompt_versions(system_prompt, interview_prompt)
    return markdown, "ai", prompt_versions, client.usage.as_metadata()


def _render_ai_markdown(
    run_context: Dict[str, Any],
    metadata: Dict[str, Any],
    data: Dict[str, Any],
) -> str | None:
    """Render model output into the same section layout as the deterministic pack."""
    questions = _string_list(data.get("likely_questions"))
    if not questions:
        return None

    section_map = [
        ("Suggested Answer Pointers", _string_list(data.get("answer_pointers"))),
        ("Technical Focus Areas", _string_list(data.get("technical_focus"))),
        ("Behavioral Questions (STAR-ready)", _string_list(data.get("behavioral_questions"))),
        ("Resume Deep-Dive Questions", _string_list(data.get("resume_deep_dive"))),
        ("Gaps and Risk Areas", _string_list(data.get("gaps_and_risks"))),
        ("30-60-90 Day Readiness Plan", _string_list(data.get("readiness_plan"))),
        ("Questions to Ask the Interviewer", _string_list(data.get("questions_to_ask"))),
    ]

    sections = [
        f"# CandidateId\n{run_context.get('candidate_id', '')}",
        f"# Role Snapshot\n- Company: {metadata.get('company', '')}\n- Role: {metadata.get('role_title', '')}",
        "# Top 10 Likely Interview Questions\n"
        + "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions[:10])),
    ]
    for heading, items in section_map:
        if items:
            sections.append(f"# {heading}\n" + "\n".join(f"- {item}" for item in items))
    return "\n\n".join(sections)


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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