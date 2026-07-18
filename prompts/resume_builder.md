# Prompt: Resume Builder (WF03)

Generate a tailored resume package for the active candidate using only verified candidate facts and the target job description.

Inputs:
- Runtime context from WF01
- Job artifacts from WF02: `JD.txt` and `metadata.json`
- Candidate master resume source

Rules:
- Never invent experience, dates, employers, metrics, tools, certifications, or projects.
- Preserve factual consistency with the candidate profile and master resume.
- Reorder and emphasize existing facts only.
- Keep the output concise enough for a one-page resume unless config explicitly allows otherwise.

Output sections:
1. Match Keywords Found
2. Updated Professional Summary
3. Skills Order
4. Evidence-Based Experience Highlights
5. Remaining Gaps vs JD
6. Integrity Check

Quality bar:
- ATS-friendly headings and phrasing
- No keyword stuffing
- No cross-candidate leakage
- Clear statement of anything missing from the candidate record