"""
Skill 验证器

验证 Skill 目录结构和 SKILL.md 内容是否符合 openclaw 标准，
同时执行安全检查（符号链接拒绝、路径逃逸防护、脚本扫描）。
"""

import logging
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import List, Tuple

import yaml

from bridge.skill_models import SkillFrontmatter

logger = logging.getLogger(__name__)

# ==================== 安全限制 ====================

MAX_SKILL_MD_SIZE = 512 * 1024  # 512 KB
MAX_SINGLE_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_SKILL_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_SKILL_FILES = 100

# 脚本中的危险模式
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",  # rm -rf /
    r"mkfs\.",  # 格式化文件系统
    r"dd\s+if=.*of=/dev/",  # 磁盘写入
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r"chmod\s+-R\s+777\s+/",  # 递归 world-writable
    r"curl.*\|\s*(ba)?sh",  # pipe-to-shell
    r"wget.*\|\s*(ba)?sh",  # pipe-to-shell
    r"eval\s*\(\s*base64",  # eval base64
]

# 禁止的文件扩展名
BLOCKED_EXTENSIONS = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",  # 二进制
    ".msi",
    ".dmg",
    ".pkg",
    ".deb",
    ".rpm",  # 安装包
    ".pem",
    ".key",
    ".p12",
    ".pfx",  # 证书/密钥
}

# 排除的目录
EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".DS_Store"}


def _is_path_traversal(raw_name: str) -> bool:
    """检查 ZIP 条目是否存在路径穿越风险。"""
    p = PurePosixPath(raw_name)
    if p.is_absolute():
        return True
    return any(part == ".." for part in p.parts)


# ==================== 安全检查 ====================


def check_no_symlinks(skill_dir: Path) -> List[str]:
    """拒绝 skill 目录中的任何符号链接"""
    errors = []
    for item in skill_dir.rglob("*"):
        if item.is_symlink():
            errors.append(f"检测到符号链接（已拒绝）: {item.relative_to(skill_dir)}")
    return errors


def check_path_escape(skill_dir: Path) -> List[str]:
    """确保没有文件路径逃逸出 skill 目录"""
    errors = []
    skill_dir_resolved = skill_dir.resolve()
    for item in skill_dir.rglob("*"):
        try:
            resolved = item.resolve()
            resolved.relative_to(skill_dir_resolved)
        except ValueError:
            errors.append(f"路径逃逸: {item} 解析到 {resolved}")
        except OSError:
            errors.append(f"路径解析失败: {item}")
    return errors


def check_file_sizes(skill_dir: Path) -> List[str]:
    """检查文件大小限制"""
    errors = []
    total_size = 0
    file_count = 0

    for item in skill_dir.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        # 跳过排除的目录中的文件
        if any(part in EXCLUDED_DIRS for part in item.parts):
            continue

        file_count += 1
        size = item.stat().st_size
        total_size += size

        if item.name == "SKILL.md" and size > MAX_SKILL_MD_SIZE:
            errors.append(f"SKILL.md 过大: {size} 字节（上限 {MAX_SKILL_MD_SIZE}）")
        elif size > MAX_SINGLE_FILE_SIZE:
            errors.append(f"文件过大: {item.relative_to(skill_dir)} ({size} 字节，上限 {MAX_SINGLE_FILE_SIZE})")

    if total_size > MAX_SKILL_TOTAL_SIZE:
        errors.append(f"Skill 总大小过大: {total_size} 字节（上限 {MAX_SKILL_TOTAL_SIZE}）")

    if file_count > MAX_SKILL_FILES:
        errors.append(f"文件数过多: {file_count}（上限 {MAX_SKILL_FILES}）")

    return errors


def check_blocked_extensions(skill_dir: Path) -> List[str]:
    """检查 skill 全目录禁止扩展名。"""
    errors = []
    for item in skill_dir.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        if any(part in EXCLUDED_DIRS for part in item.parts):
            continue
        if item.suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"禁止的文件类型: {item.relative_to(skill_dir)}")
    return errors


def scan_scripts(skill_dir: Path) -> Tuple[List[str], List[str]]:
    """扫描 scripts/ 目录中的危险模式"""
    errors = []
    warnings = []
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return errors, warnings

    for script_file in scripts_dir.rglob("*"):
        if not script_file.is_file() or script_file.is_symlink():
            continue

        # 检查扩展名
        if script_file.suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"禁止的文件类型: {script_file.relative_to(skill_dir)}")
            continue

        # 扫描文本文件中的危险模式
        try:
            content = script_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in DANGEROUS_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    warnings.append(
                        f"脚本 {script_file.name} 中检测到潜在危险模式: '{pattern}'"
                    )
        except Exception:
            pass

    return errors, warnings


def check_zip_safety(zip_path: Path) -> List[str]:
    """检查 .skill ZIP 文件的安全性"""
    errors = []
    total_size = 0
    file_count = 0

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                file_count += 1
                total_size += info.file_size

                # 路径穿越检查
                if _is_path_traversal(info.filename):
                    errors.append(f"ZIP 中存在路径穿越: {info.filename}")

                # 符号链接检查 (Unix external_attr)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    errors.append(f"ZIP 中存在符号链接: {info.filename}")

                # 禁止的扩展名
                ext = Path(info.filename).suffix.lower()
                if ext in BLOCKED_EXTENSIONS:
                    errors.append(f"ZIP 中包含禁止的文件类型: {info.filename}")

                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    errors.append(f"ZIP 中单文件过大: {info.filename} ({info.file_size} 字节)")

    except zipfile.BadZipFile:
        errors.append(f"无效的 ZIP 文件: {zip_path}")
        return errors

    if file_count > MAX_SKILL_FILES:
        errors.append(f"ZIP 文件数过多: {file_count}（上限 {MAX_SKILL_FILES}）")
    if total_size > MAX_SKILL_TOTAL_SIZE:
        errors.append(f"ZIP 总大小过大: {total_size} 字节（上限 {MAX_SKILL_TOTAL_SIZE}）")

    return errors


def full_security_check(skill_dir: Path) -> Tuple[List[str], List[str]]:
    """运行全部安全检查"""
    errors = []
    warnings = []

    errors.extend(check_no_symlinks(skill_dir))
    errors.extend(check_path_escape(skill_dir))
    errors.extend(check_file_sizes(skill_dir))
    errors.extend(check_blocked_extensions(skill_dir))

    script_errors, script_warnings = scan_scripts(skill_dir)
    errors.extend(script_errors)
    warnings.extend(script_warnings)

    return errors, warnings


# ==================== Skill 验证 ====================


def validate_skill(skill_dir: Path, strict: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    综合验证 Skill 目录。

    检查内容：
    1. SKILL.md 存在且以 --- frontmatter 开头
    2. YAML 解析正确，必需字段存在 (name, description)
    3. 名称格式 (lowercase-hyphen-case)
    4. 描述长度 (max 1024)
    5. 安全检查 (符号链接、路径逃逸、脚本扫描)
    6. 目录名与 frontmatter name 一致

    Args:
        skill_dir: Skill 目录路径
        strict: 如果为 True，warnings 也视为错误

    Returns:
        (is_valid, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. SKILL.md 必须存在
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append("SKILL.md 不存在")
        return False, errors, warnings

    # 2. 解析 frontmatter
    try:
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            errors.append("SKILL.md 必须以 --- frontmatter 分隔符开头")
            return False, errors, warnings

        parts = content.split("---", 2)
        if len(parts) < 3:
            errors.append("SKILL.md 缺少结束 --- 分隔符")
            return False, errors, warnings

        yaml_str = parts[1].strip()
        if not yaml_str:
            errors.append("Frontmatter 内容为空")
            return False, errors, warnings

        yaml_data = yaml.safe_load(yaml_str)
        if not isinstance(yaml_data, dict):
            errors.append("Frontmatter 必须是 YAML 映射")
            return False, errors, warnings

        # 用 Pydantic 模型验证
        frontmatter = SkillFrontmatter(**yaml_data)

    except yaml.YAMLError as e:
        errors.append(f"YAML 解析错误: {e}")
        return False, errors, warnings
    except Exception as e:
        errors.append(f"Frontmatter 验证错误: {e}")
        return False, errors, warnings

    # 3. 目录名应与 frontmatter name 一致
    if skill_dir.name != frontmatter.name:
        errors.append(
            f"目录名 '{skill_dir.name}' 与 frontmatter name '{frontmatter.name}' 不一致"
        )

    # 4. body 不为空检查
    body = parts[2].strip() if len(parts) >= 3 else ""
    if not body:
        warnings.append("SKILL.md body 为空（没有指令内容）")

    # 5. 安全检查
    sec_errors, sec_warnings = full_security_check(skill_dir)
    errors.extend(sec_errors)
    warnings.extend(sec_warnings)

    # 判断有效性
    is_valid = len(errors) == 0
    if strict and warnings:
        is_valid = False

    return is_valid, errors, warnings
