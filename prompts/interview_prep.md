# Prompt: Interview Preparation Kit

Generate a focused interview preparation kit after each submitted application.

## Inputs

- Candidate context from `config/workspace.json`
- Candidate profile from `config/candidates/<candidate_id>/profile.json`
- Job description
- Tailored resume used for application

## Output Sections

1. `CandidateId`
2. `Role Snapshot` (company, role, key expectations)
3. `Top 10 Likely Interview Questions`
4. `Suggested Answer Pointers` (bullet hints, not full scripts)
5. `Technical Focus Areas`
6. `Behavioral Questions (STAR-ready)`
7. `Resume Deep-Dive Questions`
8. `Gaps and Risk Areas` (where interviewer may probe)
9. `30-60-90 Day Readiness Plan`
10. `Questions to Ask the Interviewer`

## Constraints

- Keep guidance specific to the target role.
- Do not include fake experiences.
- Prioritize concise, actionable prep notes.
- Do not include details from another candidate.

## Length Guidance

- 1 to 2 pages equivalent in markdown.