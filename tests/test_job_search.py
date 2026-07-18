from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.agent_core.job_search import run_job_search


class JobSearchTests(unittest.TestCase):
    def test_run_job_search_normalizes_scores_and_persists_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "feeds"
            input_dir.mkdir(parents=True)

            linkedin_jobs = [
                {
                    "title": "Senior QA Automation Engineer",
                    "company": "Contoso",
                    "location": "Remote - Bangalore",
                    "url": "https://example.com/jobs/contoso-qa-1",
                    "description": "Selenium Java API Testing Jenkins TestNG Remote role for QA automation.",
                    "posted_date": "2026-07-18",
                    "skills": ["Selenium", "Java", "API Testing", "Jenkins"],
                    "experience": "5-7 years",
                },
                {
                    "title": "Manual Testing Intern",
                    "company": "Fabrikam",
                    "location": "Bangalore",
                    "url": "https://example.com/jobs/fabrikam-intern-1",
                    "description": "Manual testing internship with support work.",
                    "posted_date": "2026-07-18",
                    "skills": ["Manual Testing"],
                    "experience": "0-1 years",
                },
            ]
            indeed_jobs = [
                {
                    "job_title": "Senior QA Automation Engineer",
                    "company_name": "Contoso",
                    "job_location": "Remote - Bangalore",
                    "apply_url": "https://example.com/jobs/contoso-qa-1",
                    "summary": "Duplicate listing from another portal for Selenium Java API Testing Jenkins TestNG.",
                    "skills": "Selenium, Java, API Testing, Jenkins",
                    "experience": "6 years",
                }
            ]

            (input_dir / "linkedin.json").write_text(json.dumps(linkedin_jobs, indent=2), encoding="utf-8")
            (input_dir / "indeed.json").write_text(json.dumps(indeed_jobs, indent=2), encoding="utf-8")

            run_context = {
                "candidate_id": "shashi",
                "run_id": "wf02-test-run",
                "portal_list": ["linkedin", "indeed"],
                "candidate_profile": {
                    "experience_years": 6,
                    "skills": ["Java", "Selenium", "TestNG", "API Testing", "Jenkins"],
                },
                "candidate_preferences": {
                    "minimum_match": 80,
                    "target_roles": ["Senior QA Engineer", "QA Automation Engineer", "SDET"],
                    "required_keywords": ["selenium", "java"],
                    "preferred_keywords": ["api testing", "jenkins"],
                    "exclude_keywords": ["intern", "manual testing", "support"],
                    "locations": ["remote", "bangalore"],
                    "work_modes": ["remote", "hybrid"],
                    "platforms": ["linkedin", "indeed"],
                    "min_experience_years": 4,
                    "max_experience_years": 10,
                },
                "profile_pack": {
                    "selected_profiles": [
                        {"id": "qa_automation", "keywords": ["Selenium", "Java", "API Testing"]}
                    ]
                },
            }

            result = run_job_search(root, run_context, input_dir=input_dir)

            self.assertEqual(result.total_jobs, 2)
            self.assertEqual(result.apply_count, 1)
            self.assertEqual(result.skip_count, 1)

            jobs = json.loads(result.jobs_normalized_path.read_text(encoding="utf-8"))
            self.assertEqual(jobs[0]["decision"], "Apply")
            self.assertGreaterEqual(jobs[0]["match_score"], 80)
            self.assertEqual(jobs[1]["decision"], "Skip")
            self.assertIn("Excluded by keyword", jobs[1]["reason"])

            eligible_jobs = json.loads(result.eligible_jobs_path.read_text(encoding="utf-8"))
            self.assertEqual(len(eligible_jobs), 1)

            artifact_dir = result.output_dir / "job_artifacts" / "contoso_senior_qa_automation_engineer"
            self.assertTrue((artifact_dir / "JD.txt").exists())
            self.assertTrue((artifact_dir / "metadata.json").exists())


if __name__ == "__main__":
    unittest.main()