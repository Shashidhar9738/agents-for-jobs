# Agent Build Context: AI Job Application Platform

## 1) Mission
Build a production-grade, profile-driven AI job application platform that supports:
- Multiple candidates (currently Shashidhar and Aishwarya)
- Multiple role profiles per candidate
- Multiple job portals
- Multiple AI providers
- Resume and cover letter generation
- Assisted application execution
- Interview preparation
- Notifications and dashboard analytics

The system must be reproducible, auditable, and safe.

## 2) Global Rules (Hard Constraints)
1. Never fabricate skills, projects, work history, education, dates, certifications, compensation, visa, or outcomes.
2. Never alter factual employment dates, company names, education, or certifications.
3. Resume generation must keep one-page output unless override is explicitly configured.
4. Master resume is immutable source input.
5. Prompts are loaded from markdown files only; no hardcoded prompt text in n8n nodes.
6. Every run must be traceable through logs and metadata.
7. Every application must produce structured JSON metadata.
8. Never overwrite prior run artifacts.
9. Candidate isolation is mandatory; no cross-candidate data mixing.
10. All behavior must be configuration-driven.

## 3) Source of Truth
Use these files as authoritative inputs:
- `config/workspace.json`
- `config/candidates/<candidate_id>/profile.json`
- `config/candidates/<candidate_id>/preferences.json`
- `config/ai-models.json`
- `config/portals.json`
- `config/notifications.json`
- `config/profiles.json`
- Prompt files under `prompts/`

## 4) Required Repository Structure
Maintain this structure during implementation:

- `config/`
  - `workspace.json`
  - `ai-models.json`
  - `portals.json`
  - `notifications.json`
  - `profiles.json`
  - `candidates/<candidate_id>/profile.json`
  - `candidates/<candidate_id>/preferences.json`
- `prompts/`
- `data/candidates/<candidate_id>/resume/resume_master.pdf`
- `output/<candidate_id>/AppliedJobs.csv`
- `workflows/` (exported n8n workflow JSON files)
- `logs/` (run logs)

## 5) Artifact Storage Rules
Per job target, create folder:
- `Profiles/<candidate_id>/<profile_name>/<company>/<role>/`

Required files in each folder:
- `JD.txt`
- `metadata.json`
- `Resume.pdf`
- `Resume.docx`
- `resume.json`
- `CoverLetter.pdf`
- `CoverLetter.docx`
- `InterviewQuestions.pdf`
- `Answers.md`
- `Application.json`
- `Screenshot.png`
- `Logs.txt`

If a rerun occurs for same target, create versioned folder with timestamp suffix, never overwrite.

## 6) Runtime Context Contract
WF01 must output normalized runtime context with at least:
- `run_id`
- `started_at`
- `candidate_id`
- `candidate_profile_path`
- `candidate_preferences_path`
- `profile_pack`
- `ai_provider`
- `ai_model`
- `portal_list`
- `paths` object for prompts, resumes, outputs, logs

## 7) Workflow Catalog (Implement In Order)

### WF01 Configuration Loader
Purpose:
- Load all configuration and validate schemas.

Trigger:
- Manual trigger and cron-safe trigger.

Node Sequence:
1. Trigger
2. Read `config/workspace.json`
3. Resolve `active_candidate`
4. Read candidate profile + preferences
5. Read AI, portal, notification, profiles config
6. Validate required fields
7. Build normalized run context
8. Persist run context under logs
9. Emit to WF02

Error Handling:
- Missing file -> hard fail
- Missing required field -> hard fail
- Invalid schema -> hard fail

Retries:
- File IO retries: 2

Outputs:
- `run_context.json`

Next:
- WF02

### WF02 Job Search
Purpose:
- Search and collect jobs from all configured portals.

Trigger:
- WF01 success

Node Sequence:
1. Load run context
2. For each enabled portal:
   - Authenticate if needed
   - Search by role keywords, skills, location, experience
   - Normalize records
3. Merge portal outputs
4. Remove duplicates
5. Filter by exclusions
6. Score with job matcher prompt
7. Route Apply/Review/Skip
8. Save JD + metadata for Apply/Review
9. Emit eligible jobs to WF03

Retry Policy:
- Portal request retries: 3 with exponential backoff
- CAPTCHA path -> manual queue and continue

Outputs:
- `jobs_normalized.json`
- Stored JD files

Next:
- WF03

### WF03 Resume Generator
Purpose:
- Generate ATS-tailored resume from master resume + JD.

Node Sequence:
1. Read master resume
2. Read JD text
3. Read `prompts/resume_builder.md`
4. Generate tailored resume JSON/text via AI
5. Validate factual integrity (guardrail check)
6. Validate one-page rule
7. Render DOCX and PDF
8. Save artifacts
9. Emit to WF04

Validation Rules:
- Reject any fabricated or modified factual fields
- Reject >1 page unless allowed in config

Outputs:
- `Resume.pdf`, `Resume.docx`, `resume.json`

Next:
- WF04

### WF04 Cover Letter Generator
Purpose:
- Generate role and company specific cover letter.

Node Sequence:
1. Read JD
2. Read candidate profile
3. Read tailored resume summary
4. Read `prompts/cover_letter.md`
5. Generate cover letter
6. Validate max words and factual consistency
7. Render DOCX and PDF
8. Save artifacts
9. Emit to WF05

Outputs:
- `CoverLetter.pdf`, `CoverLetter.docx`

Next:
- WF05

### WF05 Application Executor
Purpose:
- Assist and/or automate portal application process.

Node Sequence:
1. Select portal adapter
2. Login
3. Open apply URL
4. Upload resume and cover letter
5. Answer form questions from profile
6. Submit (or draft if configured)
7. Capture screenshot and status
8. Write `Application.json`
9. Append `output/<candidate_id>/AppliedJobs.csv`
10. Emit event to WF06 and success path to WF07

Error Handling:
- Login fail -> retry then manual queue
- Rate limit/CAPTCHA -> manual queue
- Missing required unknown answer -> mark Review

Outputs:
- `Application.json`, `Screenshot.png`, tracker row

Next:
- WF06 always
- WF07 on applied success

### WF06 Notifications
Purpose:
- Notify user after application events.

Channels:
- Email
- WhatsApp

Node Sequence:
1. Read event payload
2. Format message from notification prompt
3. Send via enabled channels
4. Log delivery status

### WF07 Interview Preparation
Purpose:
- Create interview prep package for successful applications.

Node Sequence:
1. Read JD + profile + tailored resume
2. Read `prompts/interview.md`
3. Generate interview Q/A package
4. Render PDF/MD outputs
5. Save artifacts

Outputs:
- `InterviewQuestions.pdf`, `Answers.md`

### WF08 Dashboard
Purpose:
- Aggregate and present metrics.

Metrics:
- Jobs found, applied, rejected, pending
- Resume used
- AI model/provider
- Token usage and estimated cost
- Companies and conversion rate
- Interview call count

Data Sources:
- Application tracker CSV
- Workflow run logs
- Model usage metadata

### WF09 Profile Manager (Recommended)
Purpose:
- Manage reusable role profiles and keyword packs.

### WF10 ATS Validator (Recommended)
Purpose:
- Validate generated resumes for ATS safety and format consistency.

### WF11 Retry Manager (Recommended)
Purpose:
- Centralized retries and dead-letter queue.

### WF12 Cleanup and Archive (Recommended)
Purpose:
- Archive stale temporary files and rotate logs.

### WF13 Company Research (Optional)
Purpose:
- Generate company-specific context before cover letter/interview generation.

### WF14 Application Verification (Optional)
Purpose:
- Verify application actually submitted and status is captured.

### WF15 QA and Final Quality Check (Optional)
Purpose:
- Validate outputs against all rules before final marking.

## 8) Prompt System Requirements
Required prompt files:
- `prompts/system.md`
- `prompts/resume_builder.md`
- `prompts/cover_letter.md`
- `prompts/interview.md`
- `prompts/job_matcher.md`
- `prompts/validator.md`
- `prompts/application_answers.md`
- `prompts/notification.md`

Each prompt must contain:
1. Objective
2. Context
3. Input schema
4. Output schema
5. Validation rules
6. Failure conditions
7. Few-shot examples
8. Negative examples
9. Version and change notes

Prompt loading rule:
- Load markdown at runtime from file path.
- Record prompt filename and version in metadata.

## 9) Configuration Schemas (Minimum)

### `config/ai-models.json`
Required fields:
- `default`
- provider sections for openai, claude, gemini, deepseek, groq, openrouter, ollama

### `config/portals.json`
Per portal:
- credentials
- enabled flag
- search constraints

### `config/notifications.json`
Required:
- channel enable flags
- destination details

### `config/profiles.json`
Contains reusable role packs:
- `id`
- `name`
- `keywords`
- optional exclude keywords

## 10) Data Contracts

### Job Metadata JSON
Must include:
- `run_id`, `candidate_id`, `profile_name`
- `portal`, `job_url`, `company`, `role`, `location`
- `raw_jd_path`, `normalized_jd_path`
- `match_score`, `decision`, `reason`

### Application JSON
Must include:
- `run_id`
- `candidate_id`
- `profile_name`
- `company`
- `role`
- `portal`
- `job_url`
- `resume_artifact_path`
- `cover_letter_artifact_path`
- `application_status`
- `submitted_at`
- `screenshot_path`
- `errors` array
- `prompt_versions` object
- `model_usage` object

## 11) n8n Implementation Standards
1. Use one workflow per domain responsibility.
2. Name every node with action-style labels.
3. Keep all credentials in n8n credentials store, not in node text.
4. Keep hardcoded literals minimal and non-secret.
5. Include error branches for all external integrations.
6. Use retry config for HTTP and automation steps.
7. Emit consistent JSON between workflows.
8. Export each workflow JSON to `workflows/`.

## 12) Logging and Audit
Log each step:
- timestamp
- workflow id
- node name
- candidate id
- target company and role (if available)
- status
- error summary

Write:
- per-artifact `Logs.txt`
- central run log in `logs/`

## 13) Security and Secrets
1. Secrets must remain in local env files and n8n credential storage.
2. Never commit secrets.
3. Mask credentials in logs and debug output.
4. Use separate credentials by provider/portal.

## 14) Error Handling and Retry
1. External API calls: 3 retries with backoff.
2. Browser automation timeout: retry with session reset.
3. CAPTCHA/rate-limit: mark manual review.
4. Validation failure: stop downstream submit and mark failed.
5. Continue processing next jobs after isolated job failure.

## 15) Test Plan and Quality Gates

### Unit and Contract Checks
- Config schema validation
- Prompt file existence and structure validation
- Metadata contract validation

### Workflow Dry Runs
- WF01 through WF08 with one candidate
- Repeat with second candidate and ensure isolation

### Output Validation
- Resume one-page check
- No fabricated facts check
- Cover letter word limit check
- Tracker row completeness check

### End-to-End Acceptance
- At least one full run per candidate from search to interview prep
- Dashboard metrics reflect run results

## 16) Delivery Plan

### Phase 1 Foundation
1. Config files and validators
2. Runtime context loader
3. Logging framework
4. Artifact path manager

### Phase 2 Search and Match
1. Portal adapters
2. Normalization and dedupe
3. Scoring and routing

### Phase 3 Document Generation
1. Resume generator
2. ATS and one-page validator
3. Cover letter generator

### Phase 4 Application and Notification
1. Portal application automation
2. Notification integration
3. Retry and manual review queue

### Phase 5 Interview and Dashboard
1. Interview prep workflow
2. Dashboard and analytics
3. Final QA and sign-off

## 17) Definition of Done
All are required:
1. Dual-candidate runs work independently.
2. No prompt hardcoding in workflows.
3. All required artifacts generated and versioned.
4. Application JSON always produced for attempted apply actions.
5. Tracker CSV updated per candidate.
6. Logs present for every workflow run.
7. Dashboard metrics visible and correct.
8. Guardrails and validation checks pass.

## 18) Direct Instruction To Give Any Coding Agent
Use this exact prompt:

Implement the AI Job Application Platform exactly as defined in AGENT_BUILD_CONTEXT.md. Build workflow-first in n8n, fully config-driven, with strict no-fabrication rules, dual-candidate isolation (shashi and aishwarya), prompt files loaded only from prompts folder, artifact versioning, complete logging, retries, and manual-review paths. Implement phases sequentially and do not skip validation gates. After each phase, produce updated workflow JSON exports, config updates, and execution proof with sample outputs.
