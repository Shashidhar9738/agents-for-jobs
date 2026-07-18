from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest import mock

from src.agent_core.resume_generator import generate_resume_bundle


def _build_fixture(root: Path) -> tuple[Path, Dict[str, Any]]:
    """Create the WF03 input tree and return (job_artifact_dir, run_context)."""
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "resume_builder.md").write_text("resume prompt\nversion: 1.2.0", encoding="utf-8")
    (prompts_dir / "system_prompt.md").write_text("system prompt\nversion: 2.0.0", encoding="utf-8")

    resume_dir = root / "data" / "candidates" / "shashi" / "resume"
    resume_dir.mkdir(parents=True)
    (resume_dir / "resume_master.txt").write_text(
        "Shashidhar\nSenior QA Engineer\nWorked on Selenium, Java, API Testing, Jenkins and TestNG automation frameworks.\nExecuted regression and API test suites for enterprise releases.",
        encoding="utf-8",
    )

    job_artifact_dir = root / "output" / "shashi" / "wf02" / "run-1" / "job_artifacts" / "contoso_sdet"
    job_artifact_dir.mkdir(parents=True)
    (job_artifact_dir / "JD.txt").write_text(
        "Looking for a Senior QA Automation Engineer with Selenium, Java, API Testing, Jenkins, and TestNG. Remote role.",
        encoding="utf-8",
    )
    (job_artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "company": "Contoso",
                "role_title": "Senior QA Automation Engineer",
                "job_url": "https://example.com/jobs/1",
                "source": "linkedin",
                "key_required_skills": ["Selenium", "Java", "API Testing", "Jenkins"],
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
            "skills": ["Java", "Selenium", "TestNG", "API Testing", "Jenkins"],
        },
        "candidate_preferences": {
            "target_roles": ["Senior QA Automation Engineer", "SDET"],
            "required_keywords": ["Selenium", "Java"],
            "preferred_keywords": ["API Testing", "Jenkins"],
        },
        "paths": {"resume_folder": str(resume_dir)},
        "ai_provider": "openai",
        "ai_model": "gpt-4.1",
        "ai_models": {
            "default": "gpt-4.1",
            "openai": {"enabled": True, "api_key_env": "TEST_OPENAI_KEY", "model": "gpt-4.1"},
        },
    }
    return job_artifact_dir, run_context


@contextmanager
def _mock_ai_reply(content: str) -> Iterator[None]:
    """Make the configured provider return one canned completion."""
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 200},
    }
    response = mock.Mock(status_code=200, text=content)
    response.json.return_value = payload
    with mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test"}, clear=True):
        with mock.patch("requests.post", return_value=response):
            yield


class ResumeGeneratorTests(unittest.TestCase):
    def test_generate_resume_bundle_outputs_resume_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            # No credential in the environment, so this exercises the deterministic path.
            with mock.patch.dict("os.environ", {}, clear=True):
                result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertTrue(result.resume_json_path.exists())
            self.assertTrue(result.resume_docx_path.exists())
            self.assertTrue(result.resume_pdf_path.exists())

            payload = json.loads(result.resume_json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["integrity_check"]["status"], "PASS")
            self.assertIn("Selenium", payload["updated_skills_order"])
            self.assertIn("Senior QA Automation Engineer", payload["target_role"])

    def test_falls_back_to_deterministic_without_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            with mock.patch.dict("os.environ", {}, clear=True):
                result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            self.assertEqual(result.model_usage, {})

    def test_uses_ai_output_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            ai_reply = json.dumps(
                {
                    "updated_professional_summary": "Senior QA Engineer with 6 years building Selenium and API test automation.",
                    "updated_skills_order": ["Selenium", "Java", "API Testing", "Jenkins", "TestNG"],
                    "rewritten_experience_project_bullets": [
                        "Built Selenium and TestNG automation frameworks for enterprise releases.",
                        "Executed regression and API test suites across release cycles.",
                    ],
                    "match_keywords_found": ["Selenium", "Java", "API Testing"],
                    "remaining_gaps": ["No verified leadership scope in the master resume."],
                    "estimated_ats_improvement": "High",
                }
            )
            with _mock_ai_reply(ai_reply):
                result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "ai")
            self.assertEqual(result.model_usage["total_tokens"], 1000)
            self.assertEqual(result.model_usage["provider"], "openai")
            self.assertEqual(result.prompt_versions["resume_builder"]["version"], "1.2.0")
            self.assertEqual(result.prompt_versions["system"]["version"], "2.0.0")

            payload = json.loads(result.resume_json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["updated_skills_order"][0], "Selenium")
            self.assertEqual(payload["estimated_ats_improvement"], "High")

    def test_rejects_ai_output_that_fabricates_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            # "40%" and "15" appear nowhere in the master resume or profile.
            ai_reply = json.dumps(
                {
                    "updated_professional_summary": "Reduced regression cycle time by 40% across 15 enterprise releases.",
                    "updated_skills_order": ["Selenium", "Java"],
                    "rewritten_experience_project_bullets": ["Cut defect leakage by 40%."],
                }
            )
            with _mock_ai_reply(ai_reply):
                result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            payload = json.loads(result.resume_json_path.read_text(encoding="utf-8"))
            self.assertNotIn("40%", payload["updated_professional_summary"])

    def test_drops_skills_not_present_in_verified_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            ai_reply = json.dumps(
                {
                    "updated_professional_summary": "Senior QA Engineer focused on automation.",
                    "updated_skills_order": ["Selenium", "Kubernetes", "Java", "Rust"],
                    "rewritten_experience_project_bullets": ["Built Selenium automation frameworks."],
                }
            )
            with _mock_ai_reply(ai_reply):
                result = generate_resume_bundle(root, run_context, job_artifact_dir)

            payload = json.loads(result.resume_json_path.read_text(encoding="utf-8"))
            self.assertEqual(result.generation_mode, "ai")
            self.assertNotIn("Kubernetes", payload["updated_skills_order"])
            self.assertNotIn("Rust", payload["updated_skills_order"])
            self.assertIn("Selenium", payload["updated_skills_order"])

    def test_falls_back_when_provider_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_artifact_dir, run_context = _build_fixture(root)

            response = mock.Mock(status_code=500, text="server error")
            response.json.return_value = {}
            with mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test"}, clear=True):
                with mock.patch("requests.post", return_value=response), mock.patch("time.sleep"):
                    result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertEqual(result.generation_mode, "deterministic")
            self.assertTrue(result.resume_pdf_path.exists())


if __name__ == "__main__":
    unittest.main()