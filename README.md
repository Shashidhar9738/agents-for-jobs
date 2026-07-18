# AI Job Application Agent

An automation-ready workspace for searching jobs, scoring fit, generating tailored application assets, and tracking submissions with strict honesty rules.

## What This Project Does

This repository is designed for an agentic workflow that:

1. Finds relevant jobs based on role, skills, and location filters.
2. Extracts and normalizes job descriptions.
3. Scores each role against your profile.
4. Tailors resume content for ATS alignment.
5. Generates a concise, truthful cover letter.
6. Assists with application submission steps.
7. Logs all applications and outcomes.
8. Generates interview prep notes for each applied role.

## Project Structure

- `config/preferences.json`: Search and workflow preferences.
- `config/profile.json`: Candidate profile data used by prompts.
- `data/`: Input data (optional source files and intermediate data).
- `output/AppliedJobs.csv`: Application tracking output.
- `prompts/`: Prompt templates used by the agent.
- `TASK_SPEC.md`: High-level implementation requirements.

## Prompt Files

- `prompts/system_prompt.md`: Core agent behavior and constraints.
- `prompts/job_search_prompt.md`: Job discovery query and filters.
- `prompts/application_prompt.md`: Form-filling and submission behavior.
- `prompts/resume_optimizer.md`: Resume tailoring prompt.
- `prompts/cover_letter.md`: Cover letter generation prompt.
- `prompts/interview_prep.md`: Post-application interview prep prompt.

## Operating Principles

- Never fabricate skills, experience, projects, certifications, or outcomes.
- Apply only when match score meets configured threshold.
- Skip duplicate applications to the same company-role combination.
- Exclude irrelevant roles (intern, manual-only, support-only, etc.).
- Keep all generated content concise, role-relevant, and truthful.

## Recommended Workflow

1. Update `config/profile.json` with your latest profile details.
2. Update `config/preferences.json` with role, location, and filter settings.
3. Run job discovery and extract structured JD data.
4. Score jobs and keep only entries meeting threshold.
5. Generate tailored resume updates and cover letter.
6. Submit applications (manual assist or automated where allowed).
7. Append each attempt to `output/AppliedJobs.csv`.
8. Generate interview prep notes for submitted applications.

## Tracking Fields (Suggested)

Use these columns in `output/AppliedJobs.csv`:

- `Date`
- `Company`
- `Role`
- `Location`
- `JobURL`
- `Source`
- `MatchScore`
- `Status` (Applied / Skipped / Failed / Pending)
- `Reason`
- `ResumeVersion`
- `CoverLetterVersion`
- `FollowUpDate`
- `Notes`

## Safety and Compliance

- Respect platform terms of service and rate limits.
- Keep personal data secure and do not expose sensitive credentials.
- Prefer manual confirmation before final submission when uncertain.

## Next Step

Start by reviewing and customizing all templates in `prompts/` for your exact target roles and communication style.