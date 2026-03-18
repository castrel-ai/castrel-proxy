import asyncio
import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from castrel_proxy.skills.manager import SkillsManager as SkillManager
from castrel_proxy.skills.sync import SkillSyncManager


def _zip_to_b64(files: dict[str, str]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class SkillSyncTests(unittest.TestCase):
    def test_sync_request_pushes_missing_or_older_server_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")
            manager.init_skill("demo-skill", "demo")
            local_skill = manager.load_skill("demo-skill")
            sync = SkillSyncManager(skill_manager=manager)

            sent_messages: list[dict] = []

            async def _fake_send(msg: dict):
                sent_messages.append(msg)

            # Case 1: server missing skill -> should push
            request_missing = {
                "id": "req-missing",
                "type": "skill_sync_request",
                "data": {"server_manifest": {}},
            }
            asyncio.run(sync.handle_skill_sync_request(request_missing, _fake_send))
            self.assertEqual(len(sent_messages), 1)
            self.assertEqual(sent_messages[0]["type"], "skill_content_push")
            self.assertEqual(sent_messages[0]["data"]["skill_name"], "demo-skill")

            # Case 2: server has same skill but older timestamp and different hash -> should push
            sent_messages.clear()
            request_older = {
                "id": "req-older",
                "type": "skill_sync_request",
                "data": {
                    "server_manifest": {
                        "demo-skill": {
                            "content_hash": "stale",
                            "updated_at": max(0, local_skill.updated_at - 1000),
                        }
                    }
                },
            }
            asyncio.run(sync.handle_skill_sync_request(request_older, _fake_send))
            self.assertEqual(len(sent_messages), 1)

    def test_sync_request_skips_when_server_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")
            manager.init_skill("demo-skill", "demo")
            local_skill = manager.load_skill("demo-skill")
            sync = SkillSyncManager(skill_manager=manager)

            sent_messages: list[dict] = []

            async def _fake_send(msg: dict):
                sent_messages.append(msg)

            request_newer = {
                "id": "req-newer",
                "type": "skill_sync_request",
                "data": {
                    "server_manifest": {
                        "demo-skill": {
                            "content_hash": "server-newer",
                            "updated_at": local_skill.updated_at + 1000,
                        }
                    }
                },
            }

            asyncio.run(sync.handle_skill_sync_request(request_newer, _fake_send))
            self.assertEqual(len(sent_messages), 0)

    def test_pull_rejects_content_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")
            sync = SkillSyncManager(skill_manager=manager)

            message = {
                "id": "m1",
                "type": "skill_content_pull",
                "data": {
                    "skill_name": "demo-skill",
                    "skill_md_content": "---\nname: demo-skill\ndescription: x\n---\n\n# body\n",
                    "content_hash": "bad-hash",
                    "resources_zip_b64": "",
                },
            }

            result = asyncio.run(sync.handle_skill_content_pull(message))
            self.assertFalse(result["success"])
            self.assertIn("content_hash", result["data"]["error"])
            self.assertFalse((tmp_path / "skills" / "demo-skill").exists())

    def test_pull_writes_skill_on_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manager = SkillManager(skills_dir=tmp_path / "skills")
            sync = SkillSyncManager(skill_manager=manager)

            skill_md = "---\nname: demo-skill\ndescription: x\n---\n\n# body\n"
            content_hash = __import__("hashlib").sha256(skill_md.encode("utf-8")).hexdigest()
            resources = _zip_to_b64({"scripts/run.sh": "echo ok\n"})

            message = {
                "id": "m2",
                "type": "skill_content_pull",
                "data": {
                    "skill_name": "demo-skill",
                    "skill_md_content": skill_md,
                    "content_hash": content_hash,
                    "resources_zip_b64": resources,
                },
            }

            result = asyncio.run(sync.handle_skill_content_pull(message))
            self.assertTrue(result["success"])
            self.assertTrue((tmp_path / "skills" / "demo-skill" / "SKILL.md").exists())
            self.assertTrue((tmp_path / "skills" / "demo-skill" / "scripts" / "run.sh").exists())


if __name__ == "__main__":
    unittest.main()
