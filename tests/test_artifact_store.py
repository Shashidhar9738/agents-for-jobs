from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.agent_core.artifact_store import (
    REQUIRED_ARTIFACTS,
    append_log,
    build_index,
    build_manifest,
    copy_master_resume,
    resolve_target,
    slugify_segment,
)


class SlugifyTests(unittest.TestCase):
    def test_keeps_names_readable(self) -> None:
        self.assertEqual(slugify_segment("Nimbus Telecom"), "Nimbus_Telecom")
        self.assertEqual(slugify_segment("Senior SDET (Remote)"), "Senior_SDET_Remote")

    def test_strips_path_traversal_characters(self) -> None:
        self.assertNotIn("/", slugify_segment("evil/../../etc"))
        self.assertNotIn("\\", slugify_segment("evil\\..\\windows"))

    def test_empty_input_falls_back(self) -> None:
        self.assertEqual(slugify_segment("   "), "unknown")


class ResolveTargetTests(unittest.TestCase):
    def test_builds_spec_section_5_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = resolve_target(root, "shashi", "QA Automation", "Nimbus Telecom", "Senior SDET")

            self.assertEqual(
                target.directory.relative_to(root).as_posix(),
                "Profiles/shashi/QA_Automation/Nimbus_Telecom/Senior_SDET",
            )
            self.assertTrue(target.directory.exists())
            self.assertFalse(target.is_versioned_rerun)

    def test_rerun_creates_timestamped_sibling_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = resolve_target(root, "shashi", "QA", "Contoso", "SDET")
            (first.directory / "Resume.pdf").write_text("original", encoding="utf-8")

            second = resolve_target(root, "shashi", "QA", "Contoso", "SDET")

            self.assertNotEqual(first.directory, second.directory)
            self.assertTrue(second.is_versioned_rerun)
            self.assertTrue(second.directory.name.startswith("SDET__"))
            # The original artifact must survive untouched.
            self.assertEqual((first.directory / "Resume.pdf").read_text(encoding="utf-8"), "original")

    def test_empty_target_is_reused_rather_than_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = resolve_target(root, "shashi", "QA", "Contoso", "SDET")
            second = resolve_target(root, "shashi", "QA", "Contoso", "SDET")

            self.assertEqual(first.directory, second.directory)
            self.assertFalse(second.is_versioned_rerun)

    def test_candidates_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a = resolve_target(root, "shashi", "QA", "Contoso", "SDET")
            b = resolve_target(root, "aishwarya", "QA", "Contoso", "SDET")

            self.assertNotEqual(a.directory, b.directory)
            self.assertIn("shashi", a.directory.as_posix())
            self.assertIn("aishwarya", b.directory.as_posix())


class LogAndManifestTests(unittest.TestCase):
    def test_append_log_accumulates_audit_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            append_log(target, "WF03", "generate_resume", "OK", "mode=ai")
            append_log(target, "WF05", "execute_application", "Applied")

            lines = (target / "Logs.txt").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("WF03", lines[0])
            self.assertIn("generate_resume", lines[0])
            self.assertIn("Applied", lines[1])

    def test_manifest_reports_missing_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            (target / "JD.txt").write_text("jd", encoding="utf-8")
            (target / "metadata.json").write_text(
                json.dumps({"company": "Contoso", "role_title": "SDET", "source": "linkedin"}),
                encoding="utf-8",
            )

            manifest = build_manifest(target)

            self.assertFalse(manifest["is_complete"])
            self.assertEqual(manifest["company"], "Contoso")
            self.assertIn("Resume.pdf", manifest["missing"])
            self.assertEqual([item["name"] for item in manifest["files"]], ["JD.txt", "metadata.json"])
            self.assertFalse(manifest["interview_ready"])

    def test_manifest_flags_interview_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            for name in REQUIRED_ARTIFACTS:
                (target / name).write_text("x", encoding="utf-8")

            manifest = build_manifest(target)

            self.assertTrue(manifest["is_complete"])
            self.assertTrue(manifest["interview_ready"])
            self.assertEqual(manifest["missing"], [])

    def test_master_resume_copy_is_listed_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "resume_master.txt"
            master.write_text("master resume body", encoding="utf-8")
            target = root / "folder"
            target.mkdir()

            copied = copy_master_resume(target, master)
            self.assertIsNotNone(copied)
            self.assertEqual(copied.name, "MasterResume.txt")

            manifest = build_manifest(target)
            self.assertEqual(manifest["files"][0]["kind"], "master_resume")

    def test_missing_master_resume_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.assertIsNone(copy_master_resume(target, Path(temp_dir) / "nope.pdf"))


class IndexTests(unittest.TestCase):
    def test_index_is_empty_when_no_profiles_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = build_index(Path(temp_dir))
            self.assertEqual(index["total_targets"], 0)
            self.assertEqual(index["targets"], [])

    def test_index_collects_targets_across_companies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for company, role in [("Contoso", "SDET"), ("Nimbus", "QA Lead")]:
                target = resolve_target(root, "shashi", "QA", company, role)
                (target.directory / "metadata.json").write_text(
                    json.dumps({"company": company, "role_title": role, "source": "linkedin"}),
                    encoding="utf-8",
                )
                (target.directory / "JD.txt").write_text("jd", encoding="utf-8")

            index = build_index(root, "shashi")

            self.assertEqual(index["total_targets"], 2)
            self.assertEqual(index["incomplete_count"], 2)
            self.assertEqual(index["interview_ready_count"], 0)
            self.assertEqual({item["company"] for item in index["targets"]}, {"Contoso", "Nimbus"})

    def test_index_scopes_to_one_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for candidate in ("shashi", "aishwarya"):
                target = resolve_target(root, candidate, "QA", "Contoso", "SDET")
                (target.directory / "JD.txt").write_text("jd", encoding="utf-8")

            self.assertEqual(build_index(root, "shashi")["total_targets"], 1)
            self.assertEqual(build_index(root)["total_targets"], 2)


if __name__ == "__main__":
    unittest.main()
