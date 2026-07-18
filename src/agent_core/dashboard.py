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
    token_usage, estimated_cost, stage_costs = _aggregate_model_usage(application_payloads, wf02_summaries)

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
        "token_usage": token_usage,
        "estimated_cost": estimated_cost,
        "cost_by_stage": stage_costs,
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
            f"- Tokens used: {summary.get('token_usage', 0):,}",
            f"- Estimated cost: ${summary.get('estimated_cost', 0):.4f}",
            f"- Conversion rate: {summary.get('conversion_rate', 0)}%",
            f"- Interview calls: {summary.get('interview_call_count', 0)}",
            f"- Companies: {', '.join(summary.get('companies', [])) or 'None'}",
        ]
    )


def _aggregate_model_usage(
    application_payloads: List[Dict[str, Any]],
    wf02_summaries: List[Dict[str, Any]],
) -> tuple[int, float, Dict[str, Any]]:
    """Roll up token and cost telemetry recorded by each workflow stage.

    WF03/WF04 usage arrives per application via Application.json; WF02 scoring
    usage is per run and lives in the job-search summary.
    """
    total_tokens = 0
    total_cost = 0.0
    stage_costs: Dict[str, Dict[str, Any]] = {}

    def record(stage: str, usage: Dict[str, Any]) -> None:
        nonlocal total_tokens, total_cost
        tokens = int(usage.get("total_tokens", 0) or 0)
        cost = float(usage.get("estimated_cost_usd", 0.0) or 0.0)
        if not tokens and not cost:
            return
        total_tokens += tokens
        total_cost += cost
        bucket = stage_costs.setdefault(stage, {"tokens": 0, "cost_usd": 0.0, "calls": 0})
        bucket["tokens"] += tokens
        bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)
        bucket["calls"] += int(usage.get("calls", 0) or 0)

    for payload in application_payloads:
        model_usage = payload.get("model_usage")
        if not isinstance(model_usage, dict):
            continue
        stages = model_usage.get("stages")
        if isinstance(stages, dict):
            for stage_name, stage_usage in stages.items():
                if isinstance(stage_usage, dict):
                    record(stage_name, stage_usage)
        else:
            record("application", model_usage)

    for summary in wf02_summaries:
        model_usage = summary.get("model_usage")
        if isinstance(model_usage, dict):
            record("wf02_job_matching", model_usage)

    return total_tokens, round(total_cost, 6), stage_costs


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