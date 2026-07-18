# Prompt: Application Execution

Use this prompt to complete a job application flow accurately and truthfully.

## Goal

Fill job applications using profile data, upload tailored documents, and log outcomes.

## Inputs

- Candidate context from `config/workspace.json` (`active_candidate`)
- Candidate profile: `config/candidates/<candidate_id>/profile.json`
- Candidate preferences: `config/candidates/<candidate_id>/preferences.json`
- Tailored resume version for this job
- Cover letter version for this job
- Job details and URL

## Required Behavior

1. Reuse candidate profile data consistently.
2. Fill all fields honestly and do not guess unknown answers.
3. Upload the role-tailored resume.
4. Upload tailored cover letter when requested.
5. Review all required fields before submit.
6. Stop and ask for confirmation before final submission when confidence is low.
7. Ensure all submitted details belong to the active candidate only.

## Field Mapping Rules

- Name, email, phone, location: use exact profile values.
- Experience years: use documented experience only.
- Current/expected CTC or salary: use configured preference or skip if optional.
- Notice period/availability: use profile value.
- Work authorization/visa: use profile value only.
- Portfolio/GitHub/LinkedIn: use only known links.

## Sensitive Questions

- If an answer is unknown or not in profile, do not invent.
- Choose safe options like `Prefer not to answer` only when available and appropriate.
- If a mandatory unknown field blocks submission, mark as `Manual Review Required`.

## Completion Output

Return a short structured summary:

- CandidateId
- Job: company + role
- Status: Applied / Draft Saved / Failed / Skipped
- Submission time
- Confidence level (High/Medium/Low)
- Issues encountered
- Next action

## Logging

Append/update `output/<candidate_id>/AppliedJobs.csv` with the final status and reason.