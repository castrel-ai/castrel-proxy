"""
Skill Sync Manager

Handles bidirectional skill synchronization over WebSocket.
"""

import base64
import hashlib
import io
import json
import logging
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..core.client_id import get_machine_metadata
from .manager import SkillsManager, get_skills_manager
from .validator import check_zip_safety, validate_skill

logger = logging.getLogger(__name__)


class SkillSyncManager:
    """Manages bidirectional skill synchronization over WebSocket"""

    def __init__(
        self,
        skills_manager: Optional[SkillsManager] = None,
        skill_manager: Optional[SkillsManager] = None,  # alias for backward compat
    ):
        self.skills_manager = skills_manager or skill_manager or get_skills_manager()

    def build_capabilities_sync_message(self, mcp_tools: Dict[str, Any]) -> dict:
        """
        Build capabilities_sync message containing skills manifest and MCP tools.

        Args:
            mcp_tools: MCP tools dict (from MCPManager.get_all_tools())

        Returns:
            Complete capabilities_sync message
        """
        skills_info = self.skills_manager.get_skills_for_registration()
        manifest = self.skills_manager.build_sync_manifest()

        combined = json.dumps(
            {"skills": manifest.manifest_hash, "mcp": sorted(mcp_tools.keys())},
            sort_keys=True,
        )
        capabilities_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

        return {
            "id": str(uuid.uuid4()),
            "type": "capabilities_sync",
            "timestamp": int(time.time() * 1000),
            "data": {
                "skills": skills_info,
                "mcp_tools": mcp_tools,
                "capabilities_hash": capabilities_hash,
                "machine_metadata": get_machine_metadata(),
            },
        }

    def build_skill_push_message(self, skill_name: str) -> dict:
        """
        Build skill_content_push message.

        Reads SKILL.md content and packages scripts/references/assets as base64 ZIP.

        Args:
            skill_name: Name of the skill to push

        Returns:
            skill_content_push message
        """
        skill = self.skills_manager.load_skill(skill_name)
        skill_dir = Path(skill.skill_dir)

        skill_md_path = skill_dir / "SKILL.md"
        skill_md_content = skill_md_path.read_text(encoding="utf-8")

        resources_zip_b64 = self._zip_resources(skill_dir)

        return {
            "id": str(uuid.uuid4()),
            "type": "skill_content_push",
            "timestamp": int(time.time() * 1000),
            "data": {
                "skill_name": skill_name,
                "skill_md_content": skill_md_content,
                "content_hash": skill.content_hash,
                "resources_zip_b64": resources_zip_b64,
                "updated_at": skill.updated_at,
            },
        }

    async def handle_skill_sync_request(
        self, message: dict, ws_send_json: Callable
    ) -> Optional[dict]:
        """
        Handle server's skill_sync_request: compare manifests and push diffs.

        Args:
            message: skill_sync_request message
            ws_send_json: WebSocket send function

        Returns:
            None (responds via ws_send_json for each skill push)
        """
        message_id = message.get("id", "")
        data = message.get("data", {})
        server_manifest = data.get("server_manifest", {})

        logger.info(
            f"[SKILL-SYNC-REQ] Received sync request: message_id={message_id}, "
            f"server_skills={len(server_manifest)}"
        )

        local_manifest = self.skills_manager.build_sync_manifest()

        for name, entry in local_manifest.skills.items():
            server_entry = server_manifest.get(name)
            should_push = False

            if server_entry is None:
                should_push = True
            elif server_entry.get("content_hash") != entry.content_hash:
                server_updated = server_entry.get("updated_at", 0)
                if entry.updated_at > server_updated:
                    should_push = True

            if should_push:
                try:
                    push_msg = self.build_skill_push_message(name)
                    await ws_send_json(push_msg)
                    logger.info(f"[SKILL-SYNC-PUSH] Pushed skill to server: {name}")
                except Exception as e:
                    logger.error(f"[SKILL-SYNC-PUSH-ERROR] Failed to push skill '{name}': {e}")

        return None

    async def handle_skill_content_pull(self, message: dict) -> dict:
        """
        Handle server pushing a skill to local: write to disk.

        Args:
            message: skill_content_pull message

        Returns:
            Response message
        """
        message_id = message.get("id", "")
        data = message.get("data", {})
        skill_name = data.get("skill_name", "")
        skill_md_content = data.get("skill_md_content", "")
        resources_zip_b64 = data.get("resources_zip_b64", "")
        expected_hash = data.get("content_hash", "")

        logger.info(
            f"[SKILL-PULL] Receiving skill from server: message_id={message_id}, "
            f"skill_name={skill_name}"
        )

        try:
            actual_hash = hashlib.sha256(skill_md_content.encode("utf-8")).hexdigest()
            if expected_hash and expected_hash != actual_hash:
                raise ValueError("content_hash does not match SKILL.md content")

            self._write_skill_from_pull(skill_name, skill_md_content, resources_zip_b64)

            logger.info(f"[SKILL-PULL-SUCCESS] Skill written: {skill_name}")
            return {
                "id": message_id,
                "type": "skill_content_pull_result",
                "success": True,
                "data": {"skill_name": skill_name, "message": "Skill saved"},
            }

        except Exception as e:
            logger.error(f"[SKILL-PULL-ERROR] Failed to write skill '{skill_name}': {e}")
            return {
                "id": message_id,
                "type": "skill_content_pull_result",
                "success": False,
                "data": {"skill_name": skill_name, "error": str(e)},
            }

    async def handle_skill_delete_push(self, message: dict) -> dict:
        """
        Handle server instruction to delete a local skill.

        Args:
            message: skill_delete_push message

        Returns:
            Response message
        """
        message_id = message.get("id", "")
        data = message.get("data", {})
        skill_name = data.get("skill_name", "")

        logger.info(
            f"[SKILL-DELETE] Server requested skill deletion: message_id={message_id}, "
            f"skill_name={skill_name}"
        )

        try:
            self.skills_manager.remove_skill(skill_name)
            logger.info(f"[SKILL-DELETE-SUCCESS] Skill deleted: {skill_name}")
            return {
                "id": message_id,
                "type": "skill_delete_push_result",
                "success": True,
                "data": {"skill_name": skill_name, "message": "Skill deleted"},
            }
        except Exception as e:
            logger.error(f"[SKILL-DELETE-ERROR] Failed to delete skill '{skill_name}': {e}")
            return {
                "id": message_id,
                "type": "skill_delete_push_result",
                "success": False,
                "data": {"skill_name": skill_name, "error": str(e)},
            }

    # ==================== Internal helpers ====================

    def _zip_resources(self, skill_dir: Path) -> str:
        """
        Package skill's scripts/, references/, assets/ as base64-encoded ZIP.

        Returns:
            Base64-encoded ZIP string, or empty string if no resources
        """
        resource_dirs = ["scripts", "references", "assets"]
        has_resources = False

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dir_name in resource_dirs:
                dir_path = skill_dir / dir_name
                if not dir_path.is_dir():
                    continue
                for item in dir_path.rglob("*"):
                    if item.is_file() and not item.is_symlink():
                        arcname = str(item.relative_to(skill_dir))
                        zf.write(item, arcname)
                        has_resources = True

        if not has_resources:
            return ""

        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _write_skill_from_pull(
        self, skill_name: str, skill_md_content: str, resources_zip_b64: str
    ) -> None:
        """
        Write server-pushed skill content to local disk.

        Uses a staging directory + atomic copy to avoid half-written state.

        Args:
            skill_name: Skill name
            skill_md_content: SKILL.md content
            resources_zip_b64: Base64-encoded resources ZIP
        """
        self.skills_manager._ensure_skills_dir()
        target_dir = self.skills_manager._get_skill_dir(skill_name)

        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / skill_name
            staging_dir.mkdir(parents=True)

            (staging_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

            if resources_zip_b64:
                zip_data = base64.b64decode(resources_zip_b64, validate=True)
                buf = io.BytesIO(zip_data)

                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    tmp.write(zip_data)
                    tmp_path = Path(tmp.name)

                try:
                    errors = check_zip_safety(tmp_path)
                    if errors:
                        raise ValueError(f"ZIP safety check failed: {'; '.join(errors)}")
                finally:
                    tmp_path.unlink(missing_ok=True)

                with zipfile.ZipFile(buf, "r") as zf:
                    zf.extractall(staging_dir)

            # Ensure resource directories exist
            for dir_name in ["scripts", "references", "assets"]:
                (staging_dir / dir_name).mkdir(exist_ok=True)

            # Validate frontmatter name matches skill_name
            frontmatter, _ = self.skills_manager._parse_skill_md(staging_dir / "SKILL.md")
            if frontmatter.name != skill_name:
                raise ValueError(
                    f"skill_name '{skill_name}' does not match frontmatter name '{frontmatter.name}'"
                )

            is_valid, errors, warnings = validate_skill(staging_dir, strict=False)
            if not is_valid:
                raise ValueError("Skill content validation failed: " + "; ".join(errors))
            if warnings:
                logger.warning(
                    "[SKILL-PULL-WARN] Skill has warnings: %s",
                    "; ".join(warnings),
                )

            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(staging_dir, target_dir)
