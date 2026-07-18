from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest import mock

from src.agent_core.cover_letter_generator import generate_cover_letter_bundle
from src.agent_core.interview_prep import generate_interview_prep
from src.agent_core.job_search import run_job_search

AI_CONFIG: Dict[str, Any] = {
    "ai_provider": "openai",
    "ai_model": "gpt-4.1",
    "ai_models": {
        "default": "gpt-4.1",
        "openai": {"enabled": True, "api_key_env": "TEST_OPENAI_KEY", "model": "gpt-4.1"},
    },
}


@contextmanager
def _mock_ai_reply(content: str) -> Iterator[None]:
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 200},
    }
    response = mock.Mock(status_code=200, text=content)
    response.json.return_value = payload
    with mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test"}, clear=True):
        with mock.patch("requests.post", return_value=response):
            yield


@contextmanager
def _no_credential() -> Iterator[None]:
    with mock.patch.dict("os.environ", {}, clear=True):
        yield


def _write_prompts(root: Path) -> None:
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for name, body in [
        ("system_prompt.md", "system\nversion: 2.0.0"),
        ("resume_builder.md", "resume\nversion: 1.2.0"),
        ("cover_letter.md", "cover letter\nversion: 1.1.0"),
        ("interview.md", "interview\nversion: 1.0.0"),
        ("job_search_prompt.md", "matcher\nversion: 3.0.0"),
    ]:
        (prompts_dir / name).write_text(body, encoding="utf-8")


class JobSearchAIScoringTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Dict[str, Any]]:
        _write_prompts(root)
        input_dir = root / "data" / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "linkedin.json").write_text(
            json.dumps(
                [
                    {
                        "role_title": "SDET",
                        "company": "Contoso",
                        "location": "Remote",
                        "job_url": "https://example.com/jobs/1",
                        "job_description": "Selenium Java API Testing automation role.",
                    },
                    {
                        "role_title": "Crypto Trader",
                        "company": "Shady Corp",
                        "location": "Remote",
                        "job_url": "https://example.com/jobs/2",
                        "job_description": "Unpaid internship in crypto trading.",
                    },
                ]
            ),
            encoding="utf-8",
        )

        run_context = {
            "candidate_id": "shashi",
            "run_id": "run-1",
            "portal_list": ["linkedin"],
            "candidate_profile": {
                "name": "Shashidhar",
                "experience_years": 6,
                "skills": ["Java", "Selenium", "API Testing"],
            },
            "candidate_preferences": {
                "minimum_match": 50,
                "target_roles": ["QA Automation Engineer"],
                "locations": ["Remote"],
                "exclude_keywords": ["unpaid"],
            },
            "profile_pack": {"selected_profiles": []},
            **AI_CONFIG,
        }
        return input_dir, run_context

    def test_blends_semantic_score_and_records_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir, run_context = self._fixture(root)

            reply = json.dumps(
                {
                    "scores": [
                        {"index": 0, "semantic_score": 90, "fit_summary": "Strong SDET alignment."}
                    ]
                }
            )
            with _mock_ai_reply(reply):
                result = run_job_search(root, run_context, input_dir)

            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["scoring_mode"], "ai_blended")
            self.assertEqual(summary["model_usage"]["total_tokens"], 700)
            self.assertEqual(summary["prompt_versions"]["job_matcher"]["version"], "3.0.0")

            jobs = json.loads(result.jobs_normalized_path.read_text(encoding="utf-8"))
            sdet = next(job for job in jobs if job["role_title"] == "SDET")
            self.assertEqual(sdet["semantic_score"], 90)
            self.assertIn("deterministic_score", sdet)
            self.assertEqual(sdet["fit_summary"], "Strong SDET alignment.")

    def test_excluded_job_is_never_sent_to_model_or_revived(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir, run_context = self._fixture(root)

            # The model tries to score the excluded job highly; it must be ignored.
            reply = json.dumps(
                {
                    "scores": [
                        {"index": 0, "semantic_score": 95, "fit_summary": "Great fit."},
                        {"index": 1, "semantic_score": 99, "fit_summary": "Also great."},
                    ]
                }
            )
            with _mock_ai_reply(reply) as _:
                result = run_job_search(root, run_context, input_dir)

            jobs = json.loads(result.jobs_normalized_path.read_text(encoding="utf-8"))
            excluded = next(job for job in jobs if job["company"] == "Shady Corp")
            self.assertEqual(excluded["decision"], "Skip")
            self.assertEqual(excluded["match_score"], 0)
            self.assertTrue(excluded["hard_filtered"])
            self.assertNotIn("semantic_score", excluded)

    def test_excluded_job_absent_from_model_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir, run_context = self._fixture(root)

            reply = json.dumps({"scores": [{"index": 0, "semantic_score": 80}]})
            payload = {
                "choices": [{"message": {"content": reply}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
            response = mock.Mock(status_code=200, text=reply)
            response.json.return_value = payload

            with mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test"}, clear=True):
                with mock.patch("requests.post", return_value=response) as post:
                    run_job_search(root, run_context, input_dir)

            sent_prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
            self.assertIn("SDET", sent_prompt)
            self.assertNotIn("Shady Corp", sent_prompt)

    def test_falls_back_to_deterministic_without_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir, run_context = self._fixture(root)

            with _no_credential():
                result = run_job_search(root, run_context, input_dir)

            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["scoring_mode"], "deterministic")

    def test_malformed_score_entries_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir, run_context = self._fixture(root)

            reply = json.dumps({"scores": [{"index": "nope", "semantic_score": "high"}]})
            with _mock_ai_reply(reply):
                result = run_job_search(root, run_context, input_dir)

            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["scoring_mode"], "deterministic")


def _document_fixture(root: Path) -> tuple[Path, Dict[str, Any]]:
    _write_prompts(root)
    job_artifact_dir = root / "artifacts" / "contoso"
    job_artifact_dir.mkdir(parents=True)
    (job_artifact_dir / "JD.txt").write_text(
        "Senior QA Automation Engineer needing Selenium, Java, and API Testing.", encoding="utf-8"
    )
    (job_artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "company": "Contoso",
                "role_title": "Senior QA Automation Engineer",
                "location": "Remote",
                "source": "linkedin",
            }
        ),
        encoding="utf-8",
    )
    # The deterministic baseline must clear its own 220-word floor, so this fixture
    # carries a realistically detailed summary rather than a one-line stub.
    (job_artifact_dir / "resume.json").write_text(
        json.dumps(
            {
                "updated_professional_summary": (
                    "Senior QA Engineer with 6 years of experience designing and maintaining "
                    "automation frameworks across enterprise web and API surfaces. Focused on "
                    "building durable Selenium and TestNG suites, expanding API regression "
                    "coverage, and integrating quality gates into Jenkins delivery pipelines so "
                    "release risk is visible early. Comfortable partnering with developers and "
                    "product stakeholders to triage defects, clarify acceptance criteria, and "
                    "keep test signal trustworthy under release pressure. Emphasizes verified "
                    "strengths in test design, debugging, and framework maintainability while "
                    "staying aligned to the requirements stated in the job description."
                ),
                "updated_skills_order": ["Selenium", "Java", "API Testing", "TestNG", "Jenkins"],
                "match_keywords_found": ["Selenium", "Java", "API Testing"],
                "rewritten_experience_project_bullets": [
                    "Built Selenium and TestNG automation frameworks for enterprise releases.",
                    "Executed regression and API test suites across release cycles.",
                ],
                "remaining_gaps": ["Leadership scope is not strongly evidenced."],
            }
        ),
        encoding="utf-8",
    )

    run_context = {
        "candidate_id": "shashi",
        "candidate_profile": {
            "name": "Shashidhar",
            "experience_years": 6,
            "current_title": "Senior QA Engineer",
            "skills": ["Java", "Selenium", "API Testing", "TestNG", "Jenkins"],
        },
        **AI_CONFIG,
    }
    return job_artifact_dir, run_context


def _valid_letter() -> str:
    body = " ".join(["automation quality delivery collaboration testing"] * 50)
    return (
        "Dear Hiring Team,\n\nI am applying for the Senior QA Automation Engineer role at Contoso. "
        + body
        + "\n\nSincerely,\nShashidhar"
    )


class CoverLetterAITests(unittest.TestCase):
    def test_uses_ai_letter_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            reply = json.dumps({"cover_letter_text": _valid_letter()})
            with _mock_ai_reply(reply):
                result = generate_cover_letter_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "ai")
            self.assertEqual(result.prompt_versions["cover_letter"]["version"], "1.1.0")
            self.assertEqual(result.model_usage["total_tokens"], 700)

    def test_rejects_letter_violating_word_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            reply = json.dumps({"cover_letter_text": "Dear Hiring Team,\n\nToo short.\n\nSincerely,\nShashidhar"})
            with _mock_ai_reply(reply):
                result = generate_cover_letter_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")

    def test_rejects_letter_with_fabricated_metric(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            fabricated = _valid_letter().replace("I am applying", "I cut defects by 47% and I am applying")
            reply = json.dumps({"cover_letter_text": fabricated})
            with _mock_ai_reply(reply):
                result = generate_cover_letter_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            self.assertNotIn("47%", result.cover_letter_text_path.read_text(encoding="utf-8"))

    def test_falls_back_without_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            with _no_credential():
                result = generate_cover_letter_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            self.assertTrue(result.cover_letter_pdf_path.exists())


class InterviewPrepAITests(unittest.TestCase):
    def test_uses_ai_pack_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            reply = json.dumps(
                {
                    "likely_questions": [f"Question {index} about Selenium?" for index in range(1, 11)],
                    "answer_pointers": ["Anchor answers in verified Selenium work."],
                    "technical_focus": ["Selenium", "API Testing"],
                    "behavioral_questions": ["Describe a release-blocking defect."],
                    "resume_deep_dive": ["Unpack the Selenium framework work."],
                    "gaps_and_risks": ["Leadership scope is not evidenced."],
                    "readiness_plan": ["30 days: map product flows."],
                    "questions_to_ask": ["How do you measure release quality?"],
                }
            )
            with _mock_ai_reply(reply):
                result = generate_interview_prep(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "ai")
            self.assertEqual(result.prompt_versions["interview"]["version"], "1.0.0")

            markdown = result.answers_md_path.read_text(encoding="utf-8")
            self.assertIn("Top 10 Likely Interview Questions", markdown)
            self.assertIn("Question 1 about Selenium?", markdown)

    def test_rejects_pack_with_fabricated_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            reply = json.dumps(
                {
                    "likely_questions": ["How did you lead a team of 25 engineers?"],
                    "answer_pointers": [],
                }
            )
            with _mock_ai_reply(reply):
                result = generate_interview_prep(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")

    def test_rejects_pack_without_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            with _mock_ai_reply(json.dumps({"answer_pointers": ["something"]})):
                result = generate_interview_prep(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")

    def test_falls_back_without_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _document_fixture(root)

            with _no_credential():
                result = generate_interview_prep(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            self.assertTrue(result.interview_questions_pdf_path.exists())


if __name__ == "__main__":
    unittest.main()
