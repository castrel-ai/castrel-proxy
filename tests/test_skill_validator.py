import tempfile
import unittest
from pathlib import Path

from castrel_proxy.skills.validator import validate_skill


class SkillValidatorTests(unittest.TestCase):
    def test_directory_name_must_match_frontmatter_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "wrong-name"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: right-name\ndescription: test\n---\n\n# Body\n",
                encoding="utf-8",
            )

            is_valid, errors, _warnings = validate_skill(skill_dir)

            self.assertFalse(is_valid)
            self.assertTrue(any("Directory name" in e for e in errors))

    def test_blocked_extension_is_rejected_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "good-name"
            (skill_dir / "assets").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: good-name\ndescription: test\n---\n\n# Body\n",
                encoding="utf-8",
            )
            (skill_dir / "assets" / "secret.pem").write_text("secret", encoding="utf-8")

            is_valid, errors, _warnings = validate_skill(skill_dir)

            self.assertFalse(is_valid)
            self.assertTrue(any("Blocked file type" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
