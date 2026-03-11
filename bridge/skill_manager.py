"""
Skill 管理器

核心 CRUD 操作：init, discover, load, validate, package, import, remove。
管理 ~/.castrel/skills/ 目录。
"""

import hashlib
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from bridge.skill_models import (
    SKILL_NAME_MAX_LENGTH,
    SKILL_NAME_PATTERN,
    Skill,
    SkillFrontmatter,
    SkillSyncEntry,
    SkillSyncManifest,
)
from bridge.skill_validator import (
    EXCLUDED_DIRS,
    check_zip_safety,
    full_security_check,
    validate_skill,
)

logger = logging.getLogger(__name__)


class SkillError(Exception):
    """Skill 相关错误"""
    pass


# SKILL.md 模板
SKILL_MD_TEMPLATE = """---
name: {name}
description: "{description}"
---

# {display_name}

<!-- 在此编写 Skill 指令 -->
"""


class SkillManager:
    """管理本地 Skill 存储和操作"""

    def __init__(self, skills_dir: Optional[Path] = None):
        if skills_dir is None:
            self.skills_dir = Path.home() / ".castrel" / "skills"
        else:
            self.skills_dir = Path(skills_dir)

    def _ensure_skills_dir(self) -> None:
        """确保 ~/.castrel/skills/ 目录存在"""
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _get_skill_dir(self, name: str) -> Path:
        """获取 skill 目录的绝对路径"""
        return self.skills_dir / name

    def _get_skill_md_path(self, name: str) -> Path:
        """获取 SKILL.md 的绝对路径"""
        return self.skills_dir / name / "SKILL.md"

    # ==================== CRUD ====================

    def init_skill(self, name: str, description: str = "", directory: Optional[str] = None) -> Path:
        """
        创建新的 Skill 骨架。

        创建结构：
          <dir>/<name>/
          ├── SKILL.md
          ├── scripts/
          ├── references/
          └── assets/

        Args:
            name: Skill 名称 (lowercase-hyphen-case, max 64)
            description: Skill 描述
            directory: 父目录（默认 ~/.castrel/skills/）

        Returns:
            创建的 Skill 目录路径

        Raises:
            SkillError: 验证失败或目录已存在
        """
        # 验证名称
        if not SKILL_NAME_PATTERN.match(name):
            raise SkillError(f"Skill 名称必须为 lowercase-hyphen-case 格式: '{name}'")
        if len(name) > SKILL_NAME_MAX_LENGTH:
            raise SkillError(f"Skill 名称超过 {SKILL_NAME_MAX_LENGTH} 字符")

        # 确定目标目录
        if directory:
            parent_dir = Path(directory)
        else:
            self._ensure_skills_dir()
            parent_dir = self.skills_dir

        skill_dir = parent_dir / name
        if skill_dir.exists():
            raise SkillError(f"Skill 目录已存在: {skill_dir}")

        # 创建目录结构
        skill_dir.mkdir(parents=True)
        (skill_dir / "scripts").mkdir()
        (skill_dir / "references").mkdir()
        (skill_dir / "assets").mkdir()

        # 生成显示名称
        display_name = name.replace("-", " ").title()

        # 写入 SKILL.md
        skill_md_content = SKILL_MD_TEMPLATE.format(
            name=name,
            description=description or f"{display_name} skill",
            display_name=display_name,
        )
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

        logger.info(f"Skill 已初始化: {skill_dir}")
        return skill_dir

    def discover_skills(self) -> List[str]:
        """
        扫描 skills 目录中所有有效的 Skill。

        Returns:
            Skill 名称列表（目录名）
        """
        self._ensure_skills_dir()
        skills = []
        for item in sorted(self.skills_dir.iterdir()):
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append(item.name)
        return skills

    def load_skill(self, name: str) -> Skill:
        """
        根据名称加载 Skill：解析 SKILL.md frontmatter + body。

        Args:
            name: Skill 名称

        Returns:
            Skill 对象

        Raises:
            SkillError: Skill 不存在或 SKILL.md 格式错误
        """
        skill_dir = self._get_skill_dir(name)
        skill_md_path = skill_dir / "SKILL.md"

        if not skill_md_path.exists():
            raise SkillError(f"Skill 不存在: {name}")

        # 解析 SKILL.md
        frontmatter, body = self._parse_skill_md(skill_md_path)

        # 计算哈希和时间戳
        content = skill_md_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        updated_at = int(skill_md_path.stat().st_mtime * 1000)

        return Skill(
            frontmatter=frontmatter,
            body=body,
            skill_dir=str(skill_dir.resolve()),
            has_scripts=(skill_dir / "scripts").is_dir() and any((skill_dir / "scripts").iterdir()),
            has_references=(skill_dir / "references").is_dir() and any((skill_dir / "references").iterdir()),
            has_assets=(skill_dir / "assets").is_dir() and any((skill_dir / "assets").iterdir()),
            content_hash=content_hash,
            updated_at=updated_at,
        )

    def validate(self, name: str, strict: bool = False) -> Tuple[bool, List[str], List[str]]:
        """
        验证 Skill 是否符合 openclaw 标准。

        Args:
            name: Skill 名称
            strict: 如果为 True，warnings 也视为错误

        Returns:
            (is_valid, errors, warnings)
        """
        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            return False, [f"Skill 目录不存在: {name}"], []
        return validate_skill(skill_dir, strict=strict)

    def remove_skill(self, name: str) -> None:
        """
        删除 Skill 目录。

        Args:
            name: Skill 名称

        Raises:
            SkillError: Skill 不存在
        """
        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            raise SkillError(f"Skill 不存在: {name}")

        shutil.rmtree(skill_dir)
        logger.info(f"Skill 已删除: {name}")

    def package_skill(self, name: str, output_path: Optional[Path] = None) -> Path:
        """
        将 Skill 打包为 .skill ZIP 文件。

        Args:
            name: Skill 名称
            output_path: 输出文件路径（默认 <name>.skill）

        Returns:
            创建的 .skill 文件路径

        Raises:
            SkillError: 验证失败
        """
        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            raise SkillError(f"Skill 不存在: {name}")

        # 先验证
        is_valid, errors, warnings = self.validate(name)
        if not is_valid:
            raise SkillError(f"Skill 验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

        # 安全检查
        sec_errors, _ = full_security_check(skill_dir)
        if sec_errors:
            raise SkillError(f"安全检查失败:\n" + "\n".join(f"  - {e}" for e in sec_errors))

        # 确定输出路径
        if output_path is None:
            output_path = Path.cwd() / f"{name}.skill"
        else:
            output_path = Path(output_path)

        # 创建 ZIP
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in skill_dir.rglob("*"):
                # 跳过排除的目录
                if any(part in EXCLUDED_DIRS for part in item.parts):
                    continue
                # 拒绝符号链接
                if item.is_symlink():
                    raise SkillError(f"拒绝打包符号链接: {item}")
                if item.is_file():
                    arcname = str(item.relative_to(skill_dir))
                    zf.write(item, arcname)

        logger.info(f"Skill 已打包: {output_path}")
        return output_path

    def import_skill(self, source_path: Path) -> str:
        """
        从 .skill ZIP 文件或目录导入 Skill。

        Args:
            source_path: .skill 文件或 Skill 目录路径

        Returns:
            导入的 Skill 名称

        Raises:
            SkillError: 导入失败
        """
        source_path = Path(source_path).resolve()

        if source_path.is_file() and source_path.suffix == ".skill":
            return self._import_from_zip(source_path)
        elif source_path.is_dir():
            return self._import_from_dir(source_path)
        else:
            raise SkillError(f"无法识别的导入源: {source_path}（需要 .skill 文件或目录）")

    # ==================== 同步辅助 ====================

    def compute_content_hash(self, name: str) -> str:
        """计算 SKILL.md 内容的 SHA256 哈希"""
        skill_md_path = self._get_skill_md_path(name)
        if not skill_md_path.exists():
            return ""
        return hashlib.sha256(skill_md_path.read_bytes()).hexdigest()

    def build_sync_manifest(self) -> SkillSyncManifest:
        """
        构建所有本地 Skills 的同步清单。

        Returns:
            SkillSyncManifest
        """
        skills_dict: Dict[str, SkillSyncEntry] = {}
        all_hashes = []

        for name in self.discover_skills():
            try:
                skill = self.load_skill(name)
                entry = SkillSyncEntry(
                    name=skill.frontmatter.name,
                    content_hash=skill.content_hash,
                    updated_at=skill.updated_at,
                    description=skill.frontmatter.description,
                )
                skills_dict[name] = entry
                all_hashes.append(skill.content_hash)
            except Exception as e:
                logger.warning(f"加载 Skill '{name}' 失败，跳过: {e}")

        # 计算清单总哈希
        combined = "|".join(sorted(all_hashes))
        manifest_hash = hashlib.sha256(combined.encode()).hexdigest()[:16] if all_hashes else ""

        return SkillSyncManifest(skills=skills_dict, manifest_hash=manifest_hash)

    def get_skills_for_registration(self) -> Dict[str, Dict[str, Any]]:
        """
        构建用于 submit_client_info / capabilities_sync 的 skills 字典。

        返回符合服务端 BridgeSkillInfo schema 的格式：
        {
            "skill-name": {
                "name": "skill-name",
                "description": "...",
                "skill_path": "/abs/path",
                "has_scripts": true,
                "has_references": false,
                "has_assets": false,
                "updated_at": 1709251200000
            }
        }
        """
        result: Dict[str, Dict[str, Any]] = {}

        for name in self.discover_skills():
            try:
                skill = self.load_skill(name)
                result[name] = {
                    "name": skill.frontmatter.name,
                    "description": skill.frontmatter.description,
                    "skill_path": skill.skill_dir,
                    "has_scripts": skill.has_scripts,
                    "has_references": skill.has_references,
                    "has_assets": skill.has_assets,
                    "updated_at": skill.updated_at,
                }
            except Exception as e:
                logger.warning(f"加载 Skill '{name}' 失败，跳过: {e}")

        return result

    # ==================== 内部辅助 ====================

    def _parse_skill_md(self, skill_md_path: Path) -> Tuple[SkillFrontmatter, str]:
        """
        解析 SKILL.md 为 frontmatter 和 body。

        Returns:
            (SkillFrontmatter, body_markdown)
        """
        content = skill_md_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise SkillError(f"SKILL.md 必须以 --- 开头: {skill_md_path}")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise SkillError(f"SKILL.md 缺少结束 --- 分隔符: {skill_md_path}")

        yaml_str = parts[1].strip()
        body = parts[2].strip()

        yaml_data = yaml.safe_load(yaml_str)
        if not isinstance(yaml_data, dict):
            raise SkillError(f"Frontmatter 必须是 YAML 映射: {skill_md_path}")

        frontmatter = SkillFrontmatter(**yaml_data)
        return frontmatter, body

    def _import_from_zip(self, zip_path: Path) -> str:
        """从 .skill ZIP 文件导入"""
        # 安全检查
        zip_errors = check_zip_safety(zip_path)
        if zip_errors:
            raise SkillError(f"ZIP 安全检查失败:\n" + "\n".join(f"  - {e}" for e in zip_errors))

        self._ensure_skills_dir()

        # 解压到临时目录以确定 skill 名称
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_path)

            # 查找 SKILL.md — 可能在根目录或在子目录中
            skill_md_candidates = list(tmp_path.rglob("SKILL.md"))
            if not skill_md_candidates:
                raise SkillError("ZIP 中未找到 SKILL.md")

            # 使用相对解压根目录最浅的 SKILL.md
            skill_md = min(skill_md_candidates, key=lambda p: len(p.relative_to(tmp_path).parts))
            skill_root = skill_md.parent

            # 解析获取名称
            frontmatter, _ = self._parse_skill_md(skill_md)
            name = frontmatter.name

            # 将候选内容放到与 frontmatter 一致的目录名下再校验
            candidate_dir = tmp_path / name
            if candidate_dir.exists():
                shutil.rmtree(candidate_dir)
            shutil.copytree(skill_root, candidate_dir)
            self._validate_import_candidate(candidate_dir)

            # 目标目录
            target_dir = self.skills_dir / name
            if target_dir.exists():
                shutil.rmtree(target_dir)

            # 复制
            shutil.copytree(candidate_dir, target_dir)

        logger.info(f"Skill 已从 ZIP 导入: {name}")
        return name

    def _import_from_dir(self, source_dir: Path) -> str:
        """从目录导入"""
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillError(f"目录中未找到 SKILL.md: {source_dir}")

        # 解析获取名称
        frontmatter, _ = self._parse_skill_md(skill_md)
        name = frontmatter.name

        self._validate_import_candidate(source_dir)
        self._ensure_skills_dir()
        target_dir = self.skills_dir / name
        if target_dir.exists():
            shutil.rmtree(target_dir)

        # 复制（排除特殊目录）
        shutil.copytree(
            source_dir,
            target_dir,
            ignore=shutil.ignore_patterns(*EXCLUDED_DIRS),
        )

        logger.info(f"Skill 已从目录导入: {name}")
        return name

    def _validate_import_candidate(self, candidate_dir: Path) -> None:
        """在导入前验证候选 skill 目录的结构和安全性。"""
        is_valid, errors, warnings = validate_skill(candidate_dir, strict=False)
        if not is_valid:
            raise SkillError("导入内容验证失败:\n" + "\n".join(f"  - {e}" for e in errors))
        if warnings:
            logger.warning(
                "导入内容包含警告: %s",
                "; ".join(warnings),
            )


# 全局单例
_skill_manager = SkillManager()


def get_skill_manager() -> SkillManager:
    """获取全局 SkillManager 实例"""
    return _skill_manager
