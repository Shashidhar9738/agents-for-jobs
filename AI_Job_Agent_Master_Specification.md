# AI Job Application Platform - Master Specification

## Objective

Build a production-grade AI-powered job application platform using n8n
as the workflow orchestrator.

## High-Level Requirements

1.  Store a single immutable master resume (PDF/DOCX).
2.  Store AI model credentials separately.
3.  Store job portal credentials separately.
4.  Search multiple job portals.
5.  Match jobs against configured profiles.
6.  Generate ATS-optimized one-page resumes without changing formatting.
7.  Generate tailored cover letters.
8.  Automatically apply to matching jobs.
9.  Notify via email or WhatsApp after each application.
10. Generate interview questions from the JD.
11. Store every artifact in a structured folder hierarchy.
12. Support unlimited future profiles without workflow changes.
13. Keep prompts in editable Markdown files only.

## Recommended Folder Structure

AI-Job-Agent/ config/ ai-models.json job-portals.json notifications.json
profiles.json settings.json prompts/ system.md resume-builder.md
cover-letter.md interview-questions.md job-matcher.md
application-validator.md resumes/ master/master_resume.pdf
master/master_resume.docx generated/ profiles/ applications/
cover_letters/ interview_questions/ logs/ workflows/

## Workflows

1.  Configuration Loader
2.  Job Search
3.  Resume Generator
4.  Cover Letter Generator
5.  Auto Apply
6.  Notification
7.  Interview Question Generator
8.  Dashboard

## Storage Structure

Profiles/ `<Profile>`{=html}/ `<Company>`{=html}/ JD.txt metadata.json
Resume.pdf Resume.docx CoverLetter.pdf CoverLetter.docx
InterviewQuestions.pdf Application.json Screenshot.png Logs.txt

## AI Rules (System Prompt)

-   Never fabricate information.
-   Never modify employment dates.
-   Never modify company names.
-   Never modify certifications.
-   Keep resume within one page.
-   Preserve original formatting.
-   Tailor only summary, skills ordering, projects ordering and
    keywords.
-   Create structured folders automatically.
-   Never overwrite previous applications.
-   Generate JSON metadata.
-   Log every action.

## Resume Prompt

Use the master resume and job description. Optimize for ATS. Do not
invent experience. Keep formatting identical. Maximum one page.

## Cover Letter Prompt

Maximum 350 words. Professional tone. Reference company and role. No
generic AI wording. No fake achievements.

## Interview Prompt

Generate: - Technical questions - HR questions - Behavioural questions -
STAR answers - Coding/System Design questions where applicable -
Company-specific questions

## Configuration Files

ai-models.json { "default":"gpt-4.1",
"openai":{"api_key":"","model":"gpt-4.1"},
"gemini":{"api_key":"","model":""},"claude":{"api_key":"","model":""},"ollama":{"url":"http://localhost:11434","model":""}
}

job-portals.json {
"linkedin":{"email":"","password":""},"naukri":{"email":"","password":""},"indeed":{"email":"","password":""},"foundit":{"email":"","password":""}
}

notifications.json { "email":{"enabled":true},
"whatsapp":{"enabled":false} }

profiles.json { "profiles":\[ {"id":"qa","name":"QA Automation
Engineer","keywords":\["Selenium","Java","API","JMeter"\]},
{"id":"sdet","name":"SDET","keywords":\["Automation","TestNG","CI/CD"\]},
{"id":"performance","name":"Performance
Engineer","keywords":\["JMeter","Performance"\]} \] }

## Final Goal

The platform must be modular, configurable, reusable, prompt-driven, and
scalable with no hardcoded credentials or prompts.
