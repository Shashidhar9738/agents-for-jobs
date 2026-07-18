# Prompt: Job Search and Shortlist

Use this prompt for the active candidate from `config/workspace.json`.

## Candidate Context

1. Read `active_candidate` from `config/workspace.json`.
2. Load:
	- `config/candidates/<candidate_id>/profile.json`
	- `config/candidates/<candidate_id>/preferences.json`

Use those files as the only source for role targets, skills, and exclusions.

## Search Constraints

- Target roles: `target_roles`
- Required keywords: `required_keywords`
- Preferred keywords: `preferred_keywords`
- Locations: `locations`
- Work modes: `work_modes`
- Experience range: `min_experience_years` to `max_experience_years`
- Exclusions: `exclude_keywords`
- Minimum score: `minimum_match`

## Output Format

For each job return:

1. CandidateId
2. Company
3. RoleTitle
4. Location
5. WorkMode
6. JobURL
7. Source
8. PostedDate
9. KeyRequiredSkills
10. FitSummary
11. MatchScore (0-100)
12. Decision (`Apply` / `Skip` / `Review`)
13. Reason

## Decision Rules

- Apply only when `MatchScore >= minimum_match` and critical requirements are satisfied.
- If critical requirement is unclear, mark `Review`.
- If below threshold, mark `Skip` with exact reason.

## Integrity Rules

- No fabricated facts.
- No candidate mixing.
- Keep reasons concise and evidence-based.