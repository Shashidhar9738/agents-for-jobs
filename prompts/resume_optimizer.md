# Prompt: Resume Optimizer (ATS-Safe)

Tailor resume content for a specific job description while preserving factual accuracy.

## Objective

Improve relevance and ATS compatibility for the target role without introducing false claims.

## Strict Constraints

- Do not invent any skill, project, metric, certification, or responsibility.
- Do not change employment dates, titles, or employers unless explicitly provided.
- Keep claims defensible in interviews.

## Optimization Tasks

1. Rewrite professional summary to align with target role keywords.
2. Reorder skills so the most relevant skills appear first.
3. Rewrite project/work bullets to emphasize matching responsibilities.
4. Improve action verbs and clarity.
5. Preserve concise ATS-friendly formatting.

## ATS Guidance

- Use common role keywords from JD naturally.
- Prefer plain section headings and straightforward phrasing.
- Avoid keyword stuffing and duplicate phrases.

## Output Structure

Provide the result in sections:

1. `Match Keywords Found`
2. `Updated Professional Summary`
3. `Updated Skills Order`
4. `Rewritten Experience/Project Bullets`
5. `Changes Made (Before -> After)`
6. `Integrity Check` (explicit confirmation that nothing was fabricated)

## Quality Check

End with:

- Estimated ATS improvement (Low/Medium/High)
- Remaining gaps versus JD