from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


class JobSearchError(ValueError):
    """Raised when WF02 job search inputs are invalid."""


@dataclass
class JobSearchResult:
    output_dir: Path
    jobs_normalized_path: Path
    eligible_jobs_path: Path
    summary_path: Path
    total_jobs: int
    apply_count: int
    review_count: int
    skip_count: int


def run_job_search(
    repo_root: Path,
    run_context: Dict[str, Any],
    input_dir: Path,
    output_dir: Path | None = None,
) -> JobSearchResult:
    candidate_id = str(run_context.get("candidate_id", "")).strip()
    run_id = str(run_context.get("run_id", "")).strip()
    if not candidate_id or not run_id:
        raise JobSearchError("run context must contain candidate_id and run_id")

    portal_list = run_context.get("portal_list")
    if not isinstance(portal_list, list) or not portal_list:
        raise JobSearchError("run context must contain a non-empty portal_list")

    if not input_dir.exists():
        raise JobSearchError(f"job feed input directory not found: {input_dir}")

    candidate_profile = _as_dict(run_context.get("candidate_profile"), "candidate_profile")
    candidate_preferences = _as_dict(run_context.get("candidate_preferences"), "candidate_preferences")
    profile_pack = _as_dict(run_context.get("profile_pack"), "profile_pack")

    loaded_jobs = _load_jobs_from_feeds(input_dir, portal_list, candidate_id)
    normalized_jobs = [_score_and_route_job(job, candidate_profile, candidate_preferences, profile_pack) for job in loaded_jobs]
    deduped_jobs = _dedupe_jobs(normalized_jobs)

    base_output_dir = output_dir or repo_root / "output" / candidate_id / "wf02" / run_id
    base_output_dir.mkdir(parents=True, exist_ok=True)

    jobs_normalized_path = base_output_dir / "jobs_normalized.json"
    eligible_jobs_path = base_output_dir / "eligible_jobs.json"
    summary_path = base_output_dir / "summary.json"

    apply_or_review_jobs = [job for job in deduped_jobs if job["decision"] in {"Apply", "Review"}]
    for job in apply_or_review_jobs:
        _persist_job_artifacts(base_output_dir, job)

    jobs_normalized_path.write_text(json.dumps(deduped_jobs, indent=2), encoding="utf-8")
    eligible_jobs_path.write_text(json.dumps(apply_or_review_jobs, indent=2), encoding="utf-8")

    summary = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "input_dir": str(input_dir.resolve()),
        "output_dir": str(base_output_dir.resolve()),
        "total_jobs": len(deduped_jobs),
        "apply_count": sum(1 for job in deduped_jobs if job["decision"] == "Apply"),
        "review_count": sum(1 for job in deduped_jobs if job["decision"] == "Review"),
        "skip_count": sum(1 for job in deduped_jobs if job["decision"] == "Skip"),
        "portals": sorted({job["source"] for job in deduped_jobs}),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return JobSearchResult(
        output_dir=base_output_dir,
        jobs_normalized_path=jobs_normalized_path,
        eligible_jobs_path=eligible_jobs_path,
        summary_path=summary_path,
        total_jobs=summary["total_jobs"],
        apply_count=summary["apply_count"],
        review_count=summary["review_count"],
        skip_count=summary["skip_count"],
    )


def _as_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise JobSearchError(f"run context field '{field_name}' must be an object")
    return value


def _load_jobs_from_feeds(input_dir: Path, portal_list: List[str], candidate_id: str) -> List[Dict[str, Any]]:
    all_jobs: List[Dict[str, Any]] = []
    for portal_name in portal_list:
        raw_records = _read_portal_feed(input_dir, portal_name)
        for raw_record in raw_records:
            normalized = _normalize_job(raw_record, portal_name, candidate_id)
            if normalized is not None:
                all_jobs.append(normalized)
    return all_jobs


def _read_portal_feed(input_dir: Path, portal_name: str) -> List[Dict[str, Any]]:
    candidates = [
        input_dir / f"{portal_name}.json",
        input_dir / f"{portal_name}.jsonl",
        input_dir / f"{portal_name}.csv",
    ]
    feed_path = next((path for path in candidates if path.exists()), None)
    if feed_path is None:
        return []

    if feed_path.suffix == ".json":
        payload = json.loads(feed_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ["jobs", "items", "data", "results"]:
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        raise JobSearchError(f"unsupported JSON structure in {feed_path}")

    if feed_path.suffix == ".jsonl":
        records = []
        for line in feed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
        return records

    if feed_path.suffix == ".csv":
        with feed_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    return []


def _normalize_job(raw_record: Dict[str, Any], portal_name: str, candidate_id: str) -> Dict[str, Any] | None:
    title = _first_value(raw_record, ["role_title", "title", "job_title", "position"])
    company = _first_value(raw_record, ["company", "company_name", "employer"])
    job_url = _first_value(raw_record, ["job_url", "url", "link", "apply_url"])
    location = _first_value(raw_record, ["location", "job_location", "city"])
    description = _first_value(raw_record, ["job_description", "description", "jd", "summary"])

    if not title and not company and not description:
        return None

    work_mode = _normalize_work_mode(
        _first_value(raw_record, ["work_mode", "workmode", "mode"]),
        location,
        description,
    )
    posted_date = _first_value(raw_record, ["posted_date", "posted", "date", "created_at"])
    required_skills = _normalize_string_list(
        _first_value(raw_record, ["key_required_skills", "required_skills", "skills", "technologies"])
    )
    experience_text = _first_value(raw_record, ["experience", "experience_range", "years_experience"])
    experience_min, experience_max = _parse_experience_range(experience_text)

    return {
        "candidate_id": candidate_id,
        "company": company,
        "role_title": title,
        "location": location,
        "work_mode": work_mode,
        "job_url": job_url,
        "source": portal_name,
        "posted_date": posted_date,
        "key_required_skills": required_skills,
        "job_description": description,
        "experience_min_years": experience_min,
        "experience_max_years": experience_max,
        "raw_record": raw_record,
    }


def _first_value(record: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            if joined:
                return joined
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        separators = [",", "|", "/", "\n"]
        items = [value]
        for separator in separators:
            if separator in value:
                split_items: List[str] = []
                for item in items:
                    split_items.extend(item.split(separator))
                items = split_items
        return [item.strip() for item in items if item.strip()]
    return []


def _parse_experience_range(value: str) -> Tuple[int | None, int | None]:
    if not value:
        return None, None
    matches = [int(match) for match in re.findall(r"\d+", value)]
    if not matches:
        return None, None
    if len(matches) == 1:
        return matches[0], matches[0]
    return min(matches[0], matches[1]), max(matches[0], matches[1])


def _normalize_work_mode(work_mode: str, location: str, description: str) -> str:
    text = " ".join(part for part in [work_mode, location, description] if part).lower()
    if "remote" in text:
        return "Remote"
    if "hybrid" in text:
        return "Hybrid"
    if "onsite" in text or "on-site" in text or "office" in text:
        return "Onsite"
    return work_mode.strip() if work_mode else "Unknown"


def _score_and_route_job(
    job: Dict[str, Any],
    candidate_profile: Dict[str, Any],
    candidate_preferences: Dict[str, Any],
    profile_pack: Dict[str, Any],
) -> Dict[str, Any]:
    title = str(job.get("role_title", ""))
    company = str(job.get("company", ""))
    description = str(job.get("job_description", ""))
    location = str(job.get("location", ""))
    work_mode = str(job.get("work_mode", ""))
    source = str(job.get("source", ""))
    searchable_text = " ".join([title, company, location, work_mode, description]).lower()

    candidate_skills = {skill.lower() for skill in _normalize_string_list(candidate_profile.get("skills"))}
    target_roles = [role.lower() for role in _normalize_string_list(candidate_preferences.get("target_roles"))]
    required_keywords = [keyword.lower() for keyword in _normalize_string_list(candidate_preferences.get("required_keywords"))]
    preferred_keywords = [keyword.lower() for keyword in _normalize_string_list(candidate_preferences.get("preferred_keywords"))]
    exclude_keywords = [keyword.lower() for keyword in _normalize_string_list(candidate_preferences.get("exclude_keywords"))]
    allowed_locations = [item.lower() for item in _normalize_string_list(candidate_preferences.get("locations"))]
    allowed_work_modes = [item.lower() for item in _normalize_string_list(candidate_preferences.get("work_modes"))]
    allowed_platforms = [item.lower() for item in _normalize_string_list(candidate_preferences.get("platforms"))]
    selected_profiles = profile_pack.get("selected_profiles", [])

    exclusion_hits = [keyword for keyword in exclude_keywords if keyword in searchable_text]
    if exclusion_hits:
        return _decorate_job(
            job,
            match_score=0,
            decision="Skip",
            reason=f"Excluded by keyword: {', '.join(exclusion_hits[:3])}",
            fit_summary="Job contains excluded keywords from candidate preferences.",
            matched_keywords=[],
            missing_required_keywords=[],
        )

    if allowed_platforms and source.lower() not in allowed_platforms:
        return _decorate_job(
            job,
            match_score=0,
            decision="Skip",
            reason=f"Portal '{source}' is not enabled in candidate platform preferences",
            fit_summary="Portal does not match the candidate's allowed platforms.",
            matched_keywords=[],
            missing_required_keywords=[],
        )

    title_score = _bounded_ratio_score(target_roles, searchable_text, 25)
    matched_skills = sorted(skill for skill in candidate_skills if skill in searchable_text)
    skills_score = int(round((min(len(matched_skills), max(len(candidate_skills), 1)) / max(min(len(candidate_skills), 8), 1)) * 35))
    matched_required = [keyword for keyword in required_keywords if keyword in searchable_text]
    missing_required = [keyword for keyword in required_keywords if keyword not in searchable_text]
    matched_preferred = [keyword for keyword in preferred_keywords if keyword in searchable_text]
    keyword_score = min(len(matched_required) * 8 + len(matched_preferred) * 3, 20)
    location_score = _location_score(allowed_locations, allowed_work_modes, location, work_mode)
    experience_score = _experience_score(candidate_profile, candidate_preferences, job)
    profile_score = _profile_alignment_score(selected_profiles, searchable_text)

    match_score = min(title_score + skills_score + keyword_score + location_score + experience_score + profile_score, 100)
    fit_summary = _build_fit_summary(title_score, skills_score, keyword_score, location_score, experience_score, profile_score)

    minimum_match = int(candidate_preferences.get("minimum_match", 0) or 0)
    if not title or not company or not job.get("job_url"):
        return _decorate_job(
            job,
            match_score=match_score,
            decision="Review",
            reason="Missing one or more required fields: role title, company, or job URL",
            fit_summary=fit_summary,
            matched_keywords=matched_required + matched_preferred,
            missing_required_keywords=missing_required,
        )

    if required_keywords and missing_required:
        decision = "Review" if match_score >= minimum_match else "Skip"
        reason = f"Missing required keywords: {', '.join(missing_required[:3])}"
        return _decorate_job(
            job,
            match_score=match_score,
            decision=decision,
            reason=reason,
            fit_summary=fit_summary,
            matched_keywords=matched_required + matched_preferred,
            missing_required_keywords=missing_required,
        )

    if match_score >= minimum_match:
        return _decorate_job(
            job,
            match_score=match_score,
            decision="Apply",
            reason="Meets minimum match threshold and configured constraints",
            fit_summary=fit_summary,
            matched_keywords=matched_required + matched_preferred,
            missing_required_keywords=[],
        )

    if match_score >= max(minimum_match - 10, 0):
        return _decorate_job(
            job,
            match_score=match_score,
            decision="Review",
            reason=f"Borderline score below threshold {minimum_match}",
            fit_summary=fit_summary,
            matched_keywords=matched_required + matched_preferred,
            missing_required_keywords=missing_required,
        )

    return _decorate_job(
        job,
        match_score=match_score,
        decision="Skip",
        reason=f"Match score {match_score} is below threshold {minimum_match}",
        fit_summary=fit_summary,
        matched_keywords=matched_required + matched_preferred,
        missing_required_keywords=missing_required,
    )


def _bounded_ratio_score(terms: List[str], searchable_text: str, max_score: int) -> int:
    if not terms:
        return 0
    matches = sum(1 for term in terms if term in searchable_text)
    return int(round((matches / len(terms)) * max_score))


def _location_score(
    allowed_locations: List[str],
    allowed_work_modes: List[str],
    location: str,
    work_mode: str,
) -> int:
    score = 0
    location_text = location.lower()
    work_mode_text = work_mode.lower()
    if allowed_locations and any(item in location_text for item in allowed_locations):
        score += 8
    elif not allowed_locations:
        score += 4
    if allowed_work_modes and any(item in work_mode_text for item in allowed_work_modes):
        score += 7
    elif work_mode_text == "unknown":
        score += 2
    return score


def _experience_score(
    candidate_profile: Dict[str, Any],
    candidate_preferences: Dict[str, Any],
    job: Dict[str, Any],
) -> int:
    candidate_years = int(candidate_profile.get("experience_years", 0) or 0)
    min_pref = candidate_preferences.get("min_experience_years")
    max_pref = candidate_preferences.get("max_experience_years")
    job_min = job.get("experience_min_years")
    job_max = job.get("experience_max_years")

    if job_min is None and job_max is None:
        return 6

    if min_pref is not None and candidate_years < int(min_pref):
        return 0
    if max_pref is not None and candidate_years > int(max_pref):
        return 2
    if job_min is not None and candidate_years < int(job_min):
        return 2
    if job_max is not None and candidate_years > int(job_max) + 2:
        return 5
    return 15


def _profile_alignment_score(selected_profiles: Any, searchable_text: str) -> int:
    if not isinstance(selected_profiles, list) or not selected_profiles:
        return 0
    keywords: List[str] = []
    for profile in selected_profiles:
        if not isinstance(profile, dict):
            continue
        keywords.extend(keyword.lower() for keyword in _normalize_string_list(profile.get("keywords")))
    if not keywords:
        return 0
    matches = len({keyword for keyword in keywords if keyword in searchable_text})
    return min(matches * 2, 10)


def _build_fit_summary(
    title_score: int,
    skills_score: int,
    keyword_score: int,
    location_score: int,
    experience_score: int,
    profile_score: int,
) -> str:
    parts = []
    if title_score:
        parts.append(f"role alignment {title_score}/25")
    if skills_score:
        parts.append(f"skills match {skills_score}/35")
    if keyword_score:
        parts.append(f"keyword evidence {keyword_score}/20")
    if location_score:
        parts.append(f"location/work mode {location_score}/15")
    if experience_score:
        parts.append(f"experience fit {experience_score}/15")
    if profile_score:
        parts.append(f"profile pack {profile_score}/10")
    return "; ".join(parts) if parts else "Insufficient evidence to score the job strongly."


def _decorate_job(
    job: Dict[str, Any],
    match_score: int,
    decision: str,
    reason: str,
    fit_summary: str,
    matched_keywords: List[str],
    missing_required_keywords: List[str],
) -> Dict[str, Any]:
    decorated = dict(job)
    decorated.update(
        {
            "match_score": int(match_score),
            "decision": decision,
            "reason": reason,
            "fit_summary": fit_summary,
            "matched_keywords": sorted(set(matched_keywords)),
            "missing_required_keywords": sorted(set(missing_required_keywords)),
        }
    )
    return decorated


def _dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        key = _dedupe_key(job)
        existing = deduped.get(key)
        if existing is None or job.get("match_score", 0) > existing.get("match_score", 0):
            deduped[key] = job
    return sorted(
        deduped.values(),
        key=lambda item: (item.get("decision") != "Apply", -int(item.get("match_score", 0))),
    )


def _dedupe_key(job: Dict[str, Any]) -> str:
    job_url = str(job.get("job_url", "")).strip().lower()
    if job_url:
        return job_url
    pieces = [job.get("company", ""), job.get("role_title", ""), job.get("location", "")]
    return "|".join(str(piece).strip().lower() for piece in pieces)


def _persist_job_artifacts(base_output_dir: Path, job: Dict[str, Any]) -> None:
    folder_name = _slugify(f"{job.get('company', 'unknown')}_{job.get('role_title', 'unknown')}")
    artifact_dir = base_output_dir / "job_artifacts" / folder_name
    artifact_dir.mkdir(parents=True, exist_ok=True)

    jd_path = artifact_dir / "JD.txt"
    metadata_path = artifact_dir / "metadata.json"

    jd_path.write_text(str(job.get("job_description", "")).strip(), encoding="utf-8")
    metadata = {
        "candidate_id": job.get("candidate_id"),
        "company": job.get("company"),
        "role_title": job.get("role_title"),
        "location": job.get("location"),
        "work_mode": job.get("work_mode"),
        "job_url": job.get("job_url"),
        "source": job.get("source"),
        "posted_date": job.get("posted_date"),
        "match_score": job.get("match_score"),
        "decision": job.get("decision"),
        "reason": job.get("reason"),
        "fit_summary": job.get("fit_summary"),
        "key_required_skills": job.get("key_required_skills"),
        "missing_required_keywords": job.get("missing_required_keywords"),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "job"