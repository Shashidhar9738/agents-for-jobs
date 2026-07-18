from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.agent_core.job_search import _reroute_after_blend
from src.agent_core.resume_ingest import (
    ResumeIngestError,
    _merge_profile,
    _regex_extract,
    extract_resume_text,
    find_master_resume,
    ingest_master_resume,
)

RESUME_TEXT = (
    "Shashidhar Yadala\nSenior QA Automation Engineer\n"
    "shashidhar.y@example.com | +919876543210\n\n"
    "6 years of experience in test automation.\n\n"
    "SKILLS\nJava, Selenium WebDriver, TestNG, Rest Assured, Jenkins\n"
)


def _fixture(root: Path) -> dict:
    resume_dir = root / "data" / "candidates" / "shashi" / "resume"
    resume_dir.mkdir(parents=True)
    (resume_dir / "resume_master.txt").write_text(RESUME_TEXT, encoding="utf-8")

    profile_dir = root / "config" / "candidates" / "shashi"
    profile_dir.mkdir(parents=True)
    profile_path = profile_dir / "profile.json"
    profile_path.write_text(
        json.dumps({"name": "Old Name", "skills": ["Manual Testing"], "locations": ["Remote"]}),
        encoding="utf-8",
    )

    return {
        "candidate_id": "shashi",
        "candidate_profile_path": str(profile_path),
        "paths": {"resume_folder": str(resume_dir)},
        "ai_provider": "openrouter",
        "ai_model": "openai/gpt-4.1",
        "ai_models": {
            "default": "openai/gpt-4.1",
            "openrouter": {"enabled": True, "api_key_env": "TEST_KEY", "model": "openai/gpt-4.1"},
        },
    }


class ExtractionTests(unittest.TestCase):
    def test_finds_master_resume_by_extension_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "resume_master.txt").write_text("txt", encoding="utf-8")
            self.assertEqual(find_master_resume(folder).suffix, ".txt")

    def test_returns_none_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(find_master_resume(Path(temp_dir)))

    def test_empty_file_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "resume_master.txt"
            path.write_text("   ", encoding="utf-8")
            with self.assertRaises(ResumeIngestError) as ctx:
                extract_resume_text(path)
            self.assertIn("scanned", str(ctx.exception))

    def test_regex_fallback_pulls_contact_details(self) -> None:
        extracted = _regex_extract(RESUME_TEXT)
        self.assertEqual(extracted["email"], "shashidhar.y@example.com")
        self.assertEqual(extracted["experience_years"], 6)


class MergeGuardrailTests(unittest.TestCase):
    def test_drops_skills_absent_from_resume(self) -> None:
        merged, updated, kept, rejected = _merge_profile(
            {"skills": []},
            {"skills": ["Java", "Selenium WebDriver", "Kubernetes", "Rust"]},
            RESUME_TEXT,
        )
        self.assertIn("Java", kept)
        self.assertIn("Selenium WebDriver", kept)
        # Not written anywhere in the resume - must not enter the profile.
        self.assertEqual(sorted(rejected), ["Kubernetes", "Rust"])
        self.assertNotIn("Kubernetes", merged["skills"])

    def test_preserves_preference_fields_the_resume_does_not_own(self) -> None:
        merged, _, _, _ = _merge_profile(
            {"locations": ["Remote", "Pune"], "skills": []},
            {"skills": ["Java"], "locations": ["Mars"]},
            RESUME_TEXT,
        )
        self.assertEqual(merged["locations"], ["Remote", "Pune"])

    def test_records_provenance(self) -> None:
        merged, _, _, _ = _merge_profile({}, {"name": "Shashidhar Yadala"}, RESUME_TEXT)
        self.assertEqual(merged["profile_source"]["derived_from"], "master_resume")


class IngestTests(unittest.TestCase):
    def test_ingest_updates_profile_and_archives_previous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _fixture(root)

            reply = json.dumps(
                {
                    "name": "Shashidhar Yadala",
                    "email": "shashidhar.y@example.com",
                    "current_title": "Senior QA Automation Engineer",
                    "experience_years": 6,
                    "skills": ["Java", "Selenium WebDriver", "TestNG"],
                }
            )
            response = mock.Mock(status_code=200, text=reply)
            response.json.return_value = {
                "choices": [{"message": {"content": reply}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            }
            (root / "prompts").mkdir(parents=True)
            (root / "prompts" / "system_prompt.md").write_text("sys\nversion: 1.0.0", encoding="utf-8")

            with mock.patch.dict("os.environ", {"TEST_KEY": "sk-test"}, clear=True):
                with mock.patch("requests.post", return_value=response):
                    result = ingest_master_resume(root, "shashi", context)

            self.assertEqual(result.extraction_mode, "ai")
            self.assertIn("name", result.fields_updated)
            self.assertIsNotNone(result.backup_path)
            self.assertTrue(result.backup_path.exists())

            profile = json.loads(Path(context["candidate_profile_path"]).read_text(encoding="utf-8"))
            self.assertEqual(profile["name"], "Shashidhar Yadala")
            self.assertIn("Java", profile["skills"])
            # Archived copy retains the pre-ingest state.
            self.assertEqual(json.loads(result.backup_path.read_text(encoding="utf-8"))["name"], "Old Name")

    def test_dry_run_leaves_profile_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _fixture(root)
            before = Path(context["candidate_profile_path"]).read_text(encoding="utf-8")

            with mock.patch.dict("os.environ", {}, clear=True):
                ingest_master_resume(root, "shashi", context, write=False)

            self.assertEqual(Path(context["candidate_profile_path"]).read_text(encoding="utf-8"), before)

    def test_missing_resume_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = _fixture(root)
            (Path(context["paths"]["resume_folder"]) / "resume_master.txt").unlink()

            with self.assertRaises(ResumeIngestError) as ctx:
                ingest_master_resume(root, "shashi", context)
            self.assertIn("resume_master.pdf", str(ctx.exception))


class SemanticOverrideTests(unittest.TestCase):
    def test_strong_semantic_match_routes_to_review_instead_of_skip(self) -> None:
        job = {"missing_required_keywords": []}
        _reroute_after_blend(job, blended_score=64, minimum_match=80, semantic_score=95)

        self.assertEqual(job["decision"], "Review")
        self.assertEqual(job["review_trigger"], "strong_semantic_match")

    def test_weak_semantic_match_still_skips(self) -> None:
        job = {"missing_required_keywords": []}
        _reroute_after_blend(job, blended_score=64, minimum_match=80, semantic_score=70)

        self.assertEqual(job["decision"], "Skip")
        self.assertNotIn("review_trigger", job)

    def test_override_never_promotes_straight_to_apply(self) -> None:
        job = {"missing_required_keywords": []}
        _reroute_after_blend(job, blended_score=10, minimum_match=80, semantic_score=100)

        self.assertEqual(job["decision"], "Review")

    def test_missing_required_keywords_still_caps_at_review(self) -> None:
        job = {"missing_required_keywords": ["Kubernetes"]}
        _reroute_after_blend(job, blended_score=95, minimum_match=80, semantic_score=99)

        self.assertEqual(job["decision"], "Review")

    def test_high_blend_without_semantic_override_applies(self) -> None:
        job = {"missing_required_keywords": []}
        _reroute_after_blend(job, blended_score=88, minimum_match=80, semantic_score=85)

        self.assertEqual(job["decision"], "Apply")


if __name__ == "__main__":
    unittest.main()
