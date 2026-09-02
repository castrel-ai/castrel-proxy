import tempfile
import unittest
from pathlib import Path

from castrel_proxy.skills.manager import SkillError
from castrel_proxy.skills.manager import SkillsManager as SkillManager


class SkillManagerImportTests(unittest.TestCase):
    def test_import_directory_rejects_unsafe_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")

            source = tmp_path / "unsafe-skill"
            (source / "assets").mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: unsafe-skill\ndescription: test\n---\n\n# Body\n",
                encoding="utf-8",
            )
            (source / "assets" / "private.key").write_text("k", encoding="utf-8")

            with self.assertRaises(SkillError):
                manager.import_skill(source)

    def test_import_directory_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")

            source = tmp_path / "safe-skill"
            (source / "scripts").mkdir(parents=True)
            (source / "references").mkdir(parents=True)
            (source / "assets").mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: safe-skill\ndescription: test\n---\n\n# Body\n",
                encoding="utf-8",
            )
            (source / "scripts" / "run.sh").write_text("echo ok\n", encoding="utf-8")

            name = manager.import_skill(source)
            self.assertEqual(name, "safe-skill")
            self.assertTrue((tmp_path / "skills" / "safe-skill" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
