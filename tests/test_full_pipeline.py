from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.agent_core.pipeline import run_full_pipeline


class FullPipelineTests(unittest.TestCase):
    def test_run_full_pipeline_builds_remaining_workflow_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_workspace(root)
            self._write_prompts(root)
            self._write_resume_source(root)
            self._write_job_feed(root)

            result = run_full_pipeline(root, candidate_id="shashi", job_feed_input_dir=root / "data" / "job_feeds")

            self.assertTrue(result.run_context_path.exists())
            self.assertTrue(result.dashboard_summary_path.exists())
            self.assertEqual(result.processed_jobs, 1)

            # Spec section 5 layout: Profiles/<candidate>/<profile>/<company>/<role>/
            artifact_dir = (
                root / "Profiles" / "shashi" / "QA_Automation_Engineer" / "Contoso" / "Senior_QA_Automation_Engineer"
            )
            self.assertTrue(artifact_dir.exists(), f"expected spec artifact folder at {artifact_dir}")
            self.assertTrue((artifact_dir / "JD.txt").exists())
            self.assertTrue((artifact_dir / "metadata.json").exists())
            self.assertTrue((artifact_dir / "Resume.pdf").exists())
            self.assertTrue((artifact_dir / "Resume.docx").exists())
            self.assertTrue((artifact_dir / "CoverLetter.pdf").exists())
            self.assertTrue((artifact_dir / "Application.json").exists())
            self.assertTrue((artifact_dir / "NotificationLog.json").exists())
            self.assertTrue((artifact_dir / "Logs.txt").exists())
            self.assertFalse((artifact_dir / "InterviewQuestions.pdf").exists())

            # The immutable master resume is copied in for side-by-side review.
            self.assertTrue(list(artifact_dir.glob("MasterResume.*")))

            dashboard = json.loads(result.dashboard_summary_path.read_text(encoding="utf-8"))
            self.assertEqual(dashboard["jobs_found"], 1)
            self.assertEqual(dashboard["prepared"], 1)

            self.assertIsNotNone(result.artifact_index_path)
            index = json.loads(result.artifact_index_path.read_text(encoding="utf-8"))
            self.assertEqual(index["total_targets"], 1)
            target = index["targets"][0]
            self.assertEqual(target["company"], "Contoso")
            self.assertIn("Logs.txt", [item["name"] for item in target["files"]])

    def _write_workspace(self, root: Path) -> None:
        (root / "config" / "candidates" / "shashi").mkdir(parents=True)
        (root / "data" / "candidates" / "shashi" / "resume").mkdir(parents=True)
        (root / "output" / "shashi").mkdir(parents=True)
        (root / "prompts").mkdir(parents=True)

        (root / "config" / "workspace.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "active_candidate": "shashi",
                    "candidates": {
                        "shashi": {
                            "display_name": "Shashidhar",
                            "profile_path": "config/candidates/shashi/profile.json",
                            "preferences_path": "config/candidates/shashi/preferences.json",
                            "resume_folder": "data/candidates/shashi/resume",
                            "tracker_csv": "output/shashi/AppliedJobs.csv",
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "config" / "candidates" / "shashi" / "profile.json").write_text(
            json.dumps(
                {
                    "name": "Shashidhar",
                    "email": "",
                    "phone": "",
                    "experience_years": 6,
                    "current_title": "Senior QA Engineer",
                    "skills": ["Java", "Selenium", "TestNG", "API Testing", "Jenkins"],
                    "locations": ["Remote", "Bangalore"],
                    "links": {"linkedin": "", "github": "", "portfolio": ""},
                    "resume": {
                        "master_pdf": "data/candidates/shashi/resume/resume_master.txt",
                        "base_folder": "data/candidates/shashi/resume",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "config" / "candidates" / "shashi" / "preferences.json").write_text(
            json.dumps(
                {
                    "minimum_match": 80,
                    "auto_apply": False,
                    "target_roles": ["Senior QA Automation Engineer"],
                    "required_keywords": ["Selenium", "Java"],
                    "preferred_keywords": ["API Testing", "Jenkins"],
                    "locations": ["Remote", "Bangalore"],
                    "work_modes": ["Remote", "Hybrid"],
                    "exclude_keywords": ["intern"],
                    "platforms": ["linkedin"],
                    "min_experience_years": 4,
                    "max_experience_years": 10,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "config" / "ai-models.json").write_text(
            json.dumps({"default": "gpt-4.1", "openai": {"enabled": True, "api_key_env": "OPENAI_API_KEY", "model": "gpt-4.1"}}, indent=2),
            encoding="utf-8",
        )
        (root / "config" / "portals.json").write_text(
            json.dumps({"linkedin": {"enabled": True}}, indent=2),
            encoding="utf-8",
        )
        (root / "config" / "notifications.json").write_text(
            json.dumps({"email": {"enabled": True, "provider": "gmail", "to": "", "from_env": "NOTIFICATION_EMAIL"}, "whatsapp": {"enabled": False}}, indent=2),
            encoding="utf-8",
        )
        (root / "config" / "profiles.json").write_text(
            json.dumps({"profiles": [{"id": "qa_automation", "name": "QA Automation Engineer", "keywords": ["Selenium", "Java", "API Testing"]}]}, indent=2),
            encoding="utf-8",
        )

    def _write_prompts(self, root: Path) -> None:
        prompt_files = {
            "resume_builder.md": "resume builder",
            "cover_letter.md": "cover letter",
            "notification_message.md": "notification message",
            "interview.md": "interview prep",
        }
        for name, content in prompt_files.items():
            (root / "prompts" / name).write_text(content, encoding="utf-8")

    def _write_resume_source(self, root: Path) -> None:
        (root / "data" / "candidates" / "shashi" / "resume" / "resume_master.txt").write_text(
            "Shashidhar\nSenior QA Engineer\nBuilt Selenium and Java automation suites with API Testing, Jenkins, and TestNG.\nCollaborated on release validation and defect triage across enterprise applications.",
            encoding="utf-8",
        )

    def _write_job_feed(self, root: Path) -> None:
        feed_dir = root / "data" / "job_feeds"
        feed_dir.mkdir(parents=True)
        (feed_dir / "linkedin.json").write_text(
            json.dumps(
                [
                    {
                        "title": "Senior QA Automation Engineer",
                        "company": "Contoso",
                        "location": "Remote - Bangalore",
                        "url": "https://example.com/jobs/contoso-1",
                        "description": "Looking for Selenium, Java, API Testing, Jenkins, and TestNG experience for remote QA automation work.",
                        "posted_date": "2026-07-19",
                        "skills": ["Selenium", "Java", "API Testing", "Jenkins"],
                        "experience": "5-7 years",
                    }
                ],
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()