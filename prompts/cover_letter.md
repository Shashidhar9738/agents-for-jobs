# Prompt: Tailored Cover Letter

version: 1.0.0

Generate a concise, role-specific cover letter based on the target job description and candidate profile.

Candidate source:
- Active candidate from `config/workspace.json`
- Profile from `config/candidates/<candidate_id>/profile.json`

## Constraints

- Target length: 220 to 320 words.
- Keep tone professional, confident, and direct.
- Do not fabricate achievements or responsibilities.
- Avoid generic filler and overused phrases.
- Do not mix details from the other candidate.

## Required Structure

1. Opening: role interest + company-specific motivation.
2. Body paragraph 1: strongest relevant experience and skills.
3. Body paragraph 2: role alignment and measurable impact (only factual).
4. Closing: call to action and thanks.

## Personalization Requirements

- Reference company, role title, and 2-4 JD keywords.
- Highlight only profile-backed experience.
- Mention location/work-mode fit when relevant.

## Output

- Return only the final cover letter text.
- No markdown headers.
- No placeholders left unresolved.
