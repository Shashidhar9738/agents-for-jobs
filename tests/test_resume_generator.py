from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.agent_core.resume_generator import generate_resume_bundle


class ResumeGeneratorTests(unittest.TestCase):
    def test_generate_resume_bundle_outputs_resume_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompts_dir = root / "prompts"
            prompts_dir.mkdir(parents=True)
            (prompts_dir / "resume_builder.md").write_text("resume prompt", encoding="utf-8")

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
                "paths": {
                    "resume_folder": str(resume_dir),
                },
            }

            result = generate_resume_bundle(root, run_context, job_artifact_dir)

            self.assertTrue(result.resume_json_path.exists())
            self.assertTrue(result.resume_docx_path.exists())
            self.assertTrue(result.resume_pdf_path.exists())

            payload = json.loads(result.resume_json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["integrity_check"]["status"], "PASS")
            self.assertIn("Selenium", payload["updated_skills_order"])
            self.assertIn("Senior QA Automation Engineer", payload["target_role"])


if __name__ == "__main__":
    unittest.main()