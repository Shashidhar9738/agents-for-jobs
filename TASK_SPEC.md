# Agent Task Specification

Goal:
Create an AI agent using LangGraph + Playwright + OpenAI API.

Modules:
1. Job discovery
2. JD extraction
3. Match scoring
4. Resume optimization
5. Cover letter generation
6. Browser automation
7. Application tracking
8. Notifications

Workflow:
Search -> Score -> Optimize Resume -> Cover Letter -> Apply -> Log -> Notify.

Requirements:
- Never fabricate information.
- Skip jobs below threshold.
- Avoid duplicate applications.
- Support LinkedIn Easy Apply where permitted and configurable.
- Store history in SQLite and CSV.
- Modular architecture with tests and logging.
