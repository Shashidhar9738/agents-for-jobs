from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class DashboardError(ValueError):
    """Raised when WF08 aggregation inputs are invalid."""


@dataclass
class DashboardBuildResult:
    summary_json_path: Path
    dashboard_md_path: Path


def build_dashboard(
    repo_root: Path,
    run_context: Dict[str, Any],
    output_dir: Path | None = None,
) -> DashboardBuildResult:
    candidate_id = str(run_context.get("candidate_id", "")).strip()
    if not candidate_id:
        raise DashboardError("run context is missing candidate_id")

    paths = run_context.get("paths")
    if not isinstance(paths, dict):
        raise DashboardError("run context is missing paths")
    tracker_csv_path = Path(str(paths.get("tracker_csv", ""))).resolve()
    wf02_root = repo_root / "output" / candidate_id / "wf02"

    tracker_rows = _read_csv_rows(tracker_csv_path)
    wf02_summaries = _collect_json_files(wf02_root, "summary.json")
    application_payloads = _collect_json_files(wf02_root, "Application.json")
    interview_payloads = list(wf02_root.rglob("InterviewQuestions.pdf")) if wf02_root.exists() else []

    jobs_found = sum(int(item.get("total_jobs", 0) or 0) for item in wf02_summaries)
    applied = sum(1 for row in tracker_rows if str(row.get("Status", "")) == "Applied")
    prepared = sum(1 for row in tracker_rows if str(row.get("Status", "")) == "Prepared")
    review = sum(1 for row in tracker_rows if str(row.get("Status", "")) == "Review")
    companies = sorted({str(row.get("Company", "")).strip() for row in tracker_rows if str(row.get("Company", "")).strip()})

    summary = {
        "candidate_id": candidate_id,
        "jobs_found": jobs_found,
        "applied": applied,
        "prepared": prepared,
        "review": review,
        "pending": max(len(tracker_rows) - applied, 0),
        "resume_used_count": len(application_payloads),
        "ai_provider": run_context.get("ai_provider", ""),
        "ai_model": run_context.get("ai_model", ""),
        "token_usage": 0,
        "estimated_cost": 0,
        "companies": companies,
        "conversion_rate": round((applied / jobs_found) * 100, 2) if jobs_found else 0,
        "interview_call_count": len(interview_payloads),
    }

    destination_dir = output_dir or repo_root / "output" / candidate_id / "dashboard"
    destination_dir.mkdir(parents=True, exist_ok=True)
    summary_json_path = destination_dir / "dashboard_summary.json"
    dashboard_md_path = destination_dir / "dashboard.md"
    summary_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    dashboard_md_path.write_text(_build_dashboard_markdown(summary), encoding="utf-8")
    return DashboardBuildResult(summary_json_path=summary_json_path, dashboard_md_path=dashboard_md_path)


def _build_dashboard_markdown(summary: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Dashboard - {summary.get('candidate_id', '')}",
            f"- Jobs found: {summary.get('jobs_found', 0)}",
            f"- Applied: {summary.get('applied', 0)}",
            f"- Prepared: {summary.get('prepared', 0)}",
            f"- Review: {summary.get('review', 0)}",
            f"- Pending: {summary.get('pending', 0)}",
            f"- Resume used: {summary.get('resume_used_count', 0)}",
            f"- AI provider/model: {summary.get('ai_provider', '')} / {summary.get('ai_model', '')}",
            f"- Estimated cost: {summary.get('estimated_cost', 0)}",
            f"- Conversion rate: {summary.get('conversion_rate', 0)}%",
            f"- Interview calls: {summary.get('interview_call_count', 0)}",
            f"- Companies: {', '.join(summary.get('companies', [])) or 'None'}",
        ]
    )


def _read_csv_rows(csv_path: Path) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _collect_json_files(root: Path, name: str) -> List[Dict[str, Any]]:
    if not root.exists():
        return []
    payloads = []
    for path in root.rglob(name):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads