"""
Skill 同步管理器

处理通过 WebSocket 的双向 Skill 同步。
"""

import base64
import hashlib
import io
import logging
import json
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from bridge.skill_manager import SkillManager, get_skill_manager
from bridge.skill_validator import check_zip_safety, validate_skill

logger = logging.getLogger(__name__)


class SkillSyncManager:
    """管理通过 WebSocket 的双向 Skill 同步"""

    def __init__(self, skill_manager: Optional[SkillManager] = None):
        self.skill_manager = skill_manager or get_skill_manager()

    def build_capabilities_sync_message(self, mcp_tools: Dict[str, Any]) -> dict:
        """
        构建 capabilities_sync 消息，包含 skills 清单和 MCP tools。

        Args:
            mcp_tools: MCP tools 字典 (从 MCPManager.get_all_tools() 获取)

        Returns:
            完整的 capabilities_sync 消息
        """
        skills_info = self.skill_manager.get_skills_for_registration()
        manifest = self.skill_manager.build_sync_manifest()

        # 计算综合哈希
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
            },
        }

    def build_skill_push_message(self, skill_name: str) -> dict:
        """
        构建 skill_content_push 消息。

        读取 SKILL.md 内容，并将 scripts/references/assets 打包为 base64 ZIP。

        Args:
            skill_name: 要推送的 Skill 名称

        Returns:
            skill_content_push 消息
        """
        skill = self.skill_manager.load_skill(skill_name)
        skill_dir = Path(skill.skill_dir)

        # 读取 SKILL.md 原始内容
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_content = skill_md_path.read_text(encoding="utf-8")

        # 将资源目录打包为 ZIP
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
        处理服务端的 skill_sync_request：比较清单，推送差异。

        Args:
            message: skill_sync_request 消息
            ws_send_json: WebSocket 发送函数

        Returns:
            响应消息或 None
        """
        message_id = message.get("id", "")
        data = message.get("data", {})
        server_manifest = data.get("server_manifest", {})

        logger.info(
            f"[SKILL-SYNC-REQ] Received sync request: message_id={message_id}, "
            f"server_skills={len(server_manifest)}"
        )

        # 构建本地清单
        local_manifest = self.skill_manager.build_sync_manifest()

        # 找出需要推送的 skills（本地有但服务端没有，或哈希不同且本地更新）
        for name, entry in local_manifest.skills.items():
            server_entry = server_manifest.get(name)
            should_push = False

            if server_entry is None:
                # 服务端没有此 skill
                should_push = True
            elif server_entry.get("content_hash") != entry.content_hash:
                # 哈希不同，比较时间戳
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

        return None  # 不需要直接响应

    async def handle_skill_content_pull(self, message: dict) -> dict:
        """
        处理服务端推送 skill 到本地：写入磁盘。

        Args:
            message: skill_content_pull 消息

        Returns:
            响应消息
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
                raise ValueError("content_hash 与 SKILL.md 内容不匹配")

            self._write_skill_from_pull(skill_name, skill_md_content, resources_zip_b64)

            logger.info(f"[SKILL-PULL-SUCCESS] Skill written: {skill_name}")
            return {
                "id": message_id,
                "type": "skill_content_pull_result",
                "success": True,
                "data": {"skill_name": skill_name, "message": "Skill 已保存"},
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
        处理服务端指令删除本地 skill。

        Args:
            message: skill_delete_push 消息

        Returns:
            响应消息
        """
        message_id = message.get("id", "")
        data = message.get("data", {})
        skill_name = data.get("skill_name", "")

        logger.info(
            f"[SKILL-DELETE] Server requested skill deletion: message_id={message_id}, "
            f"skill_name={skill_name}"
        )

        try:
            self.skill_manager.remove_skill(skill_name)
            logger.info(f"[SKILL-DELETE-SUCCESS] Skill deleted: {skill_name}")
            return {
                "id": message_id,
                "type": "skill_delete_push_result",
                "success": True,
                "data": {"skill_name": skill_name, "message": "Skill 已删除"},
            }
        except Exception as e:
            logger.error(f"[SKILL-DELETE-ERROR] Failed to delete skill '{skill_name}': {e}")
            return {
                "id": message_id,
                "type": "skill_delete_push_result",
                "success": False,
                "data": {"skill_name": skill_name, "error": str(e)},
            }

    # ==================== 内部辅助 ====================

    def _zip_resources(self, skill_dir: Path) -> str:
        """
        将 skill 的 scripts/, references/, assets/ 打包为 base64 编码的 ZIP。

        Args:
            skill_dir: Skill 目录路径

        Returns:
            base64 编码的 ZIP 字符串，如果没有资源则返回空字符串
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
        将服务端推送的 skill 内容写入本地磁盘。

        Args:
            skill_name: Skill 名称
            skill_md_content: SKILL.md 内容
            resources_zip_b64: base64 编码的资源 ZIP
        """
        self.skill_manager._ensure_skills_dir()
        target_dir = self.skill_manager._get_skill_dir(skill_name)

        # 先写入临时目录并校验，成功后再原子替换，避免半写入状态
        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_dir = Path(tmp_dir) / skill_name
            staging_dir.mkdir(parents=True)

            # 写入 SKILL.md
            (staging_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

            # 解压资源 ZIP
            if resources_zip_b64:
                zip_data = base64.b64decode(resources_zip_b64, validate=True)
                buf = io.BytesIO(zip_data)

                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    tmp.write(zip_data)
                    tmp_path = Path(tmp.name)

                try:
                    errors = check_zip_safety(tmp_path)
                    if errors:
                        raise ValueError(f"ZIP 安全检查失败: {'; '.join(errors)}")
                finally:
                    tmp_path.unlink(missing_ok=True)

                with zipfile.ZipFile(buf, "r") as zf:
                    zf.extractall(staging_dir)

            # 确保资源目录存在
            for dir_name in ["scripts", "references", "assets"]:
                (staging_dir / dir_name).mkdir(exist_ok=True)

            # 校验 frontmatter 与目录名一致
            frontmatter, _ = self.skill_manager._parse_skill_md(staging_dir / "SKILL.md")
            if frontmatter.name != skill_name:
                raise ValueError(
                    f"skill_name '{skill_name}' 与 frontmatter.name '{frontmatter.name}' 不一致"
                )

            is_valid, errors, warnings = validate_skill(staging_dir, strict=False)
            if not is_valid:
                raise ValueError("Skill 内容验证失败: " + "; ".join(errors))
            if warnings:
                logger.warning(
                    "[SKILL-PULL-WARN] Skill has warnings: %s",
                    "; ".join(warnings),
                )

            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(staging_dir, target_dir)
