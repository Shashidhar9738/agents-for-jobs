# AI Job Application Agent (Dual Candidate)

Automation-ready workspace for two candidates (Shashidhar and Aishwarya) to search, score, tailor, and track job applications with strict honesty and no-fabrication rules.

## What This Project Does

1. Finds relevant jobs per candidate profile and preferences.
2. Extracts and normalizes JD content.
3. Calculates transparent match scores.
4. Tailors resume content safely for ATS alignment.
5. Generates concise, truthful cover letters.
6. Assists with application execution.
7. Logs each application by candidate.
8. Generates interview prep for submitted applications.

## Candidate-Aware Structure

- `config/workspace.json`: Candidate registry and active candidate.
- `config/candidates/shashi/profile.json`: Shashidhar profile.
- `config/candidates/shashi/preferences.json`: Shashidhar search preferences.
- `config/candidates/aishwarya/profile.json`: Aishwarya profile.
- `config/candidates/aishwarya/preferences.json`: Aishwarya search preferences.
- `data/candidates/shashi/resume/`: Shashidhar resume PDFs.
- `data/candidates/aishwarya/resume/`: Aishwarya resume PDFs.
- `output/shashi/AppliedJobs.csv`: Shashidhar tracker.
- `output/aishwarya/AppliedJobs.csv`: Aishwarya tracker.
- `prompts/`: Reusable prompts for both candidates.
- `TASK_SPEC.md`: Workflow and implementation requirements.

## Prompt Files

- `prompts/system_prompt.md`
- `prompts/job_search_prompt.md`
- `prompts/application_prompt.md`
- `prompts/resume_optimizer.md`
- `prompts/cover_letter.md`
- `prompts/interview_prep.md`

## Setup Checklist (For Both Users)

1. Fill profile files:
	- `config/candidates/shashi/profile.json`
	- `config/candidates/aishwarya/profile.json`
2. Fill preference files:
	- `config/candidates/shashi/preferences.json`
	- `config/candidates/aishwarya/preferences.json`
3. Place resume PDFs:
	- `data/candidates/shashi/resume/resume_master.pdf`
	- `data/candidates/aishwarya/resume/resume_master.pdf`
4. Update `config/workspace.json` -> `active_candidate` to run one candidate at a time.

## Operating Rules

- Never fabricate skills, experience, projects, dates, or outcomes.
- Skip jobs below threshold.
- Skip duplicates (company + role + location + candidate).
- Keep generated text concise, role-specific, and factual.
- Confirm before irreversible submit actions when confidence is low.

## Suggested Run Flow

1. Select candidate via `config/workspace.json`.
2. Run job discovery using candidate preferences.
3. Score and filter by minimum match.
4. Generate resume-tailored bullets and cover letter.
5. Apply manually/assisted.
6. Write results to candidate-specific `AppliedJobs.csv`.
7. Generate interview prep for applied jobs.

## Tracker Columns

`Date,CandidateId,Company,Role,Location,JobURL,Source,MatchScore,Status,Reason,ResumeVersion,CoverLetterVersion,FollowUpDate,Notes`

## Security Notes

- Keep keys and secrets only in local `.env` and local credential JSON.
- Do not commit secret files.
- Respect platform ToS and rate limits.