# Prompt: Job Search and Shortlist

Search for jobs using the following constraints.

## Target Roles

- Senior QA Engineer
- SDET
- Automation Test Engineer
- QA Automation Engineer

## Required Skill Keywords

- Selenium
- Java
- API Testing
- JMeter
- Test Automation Frameworks

## Preferred Additional Keywords

- Rest Assured
- TestNG or JUnit
- CI/CD
- Jenkins
- SQL
- Agile

## Locations and Work Mode

- Remote
- Bangalore
- Hyderabad
- Chennai
- Pune

## Exclusion Criteria

- Intern or Internship roles
- Manual testing only roles
- Technical support or customer support roles
- Positions with no automation requirement

## Seniority and Experience

- Mid-Senior to Senior preferred
- Ignore fresher-only or 0-1 year roles

## Output Format

For each job, return:

1. Company
2. Role title
3. Location
4. Work mode (Remote/Hybrid/Onsite)
5. Job URL
6. Source platform
7. Posted date (if available)
8. Key required skills
9. Quick fit summary (2-3 lines)
10. Match score (0-100)
11. Decision (`Apply` or `Skip`)
12. Skip reason (if skipped)

## Decision Rule

- Apply only when score >= configured threshold (default 80).
- If mandatory requirements are unclear, mark as `Review` before applying.