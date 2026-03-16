"""
Skill Validator

Validates skill directory structure and SKILL.md content against the Agent Skills standard.
Performs security checks: symlink rejection, path traversal protection, script scanning.
"""

import logging
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import List, Tuple

import yaml

logger = logging.getLogger(__name__)

# ==================== Security limits ====================

MAX_SKILL_MD_SIZE = 512 * 1024       # 512 KB
MAX_SINGLE_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_SKILL_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_SKILL_FILES = 100

# Dangerous patterns in scripts
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",              # rm -rf /
    r"mkfs\.",                    # format filesystem
    r"dd\s+if=.*of=/dev/",        # disk write
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # fork bomb
    r"chmod\s+-R\s+777\s+/",     # recursive world-writable
    r"curl.*\|\s*(ba)?sh",        # pipe-to-shell
    r"wget.*\|\s*(ba)?sh",        # pipe-to-shell
    r"eval\s*\(\s*base64",        # eval base64
]

# Blocked file extensions
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib",       # binaries
    ".msi", ".dmg", ".pkg", ".deb", ".rpm",  # installers
    ".pem", ".key", ".p12", ".pfx",        # certificates/keys
}

# Excluded directories
EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".DS_Store"}


def _is_path_traversal(raw_name: str) -> bool:
    """Check whether a ZIP entry has path traversal risk."""
    p = PurePosixPath(raw_name)
    if p.is_absolute():
        return True
    return any(part == ".." for part in p.parts)


# ==================== Security checks ====================


def check_no_symlinks(skill_dir: Path) -> List[str]:
    """Reject any symlinks inside the skill directory"""
    errors = []
    for item in skill_dir.rglob("*"):
        if item.is_symlink():
            errors.append(f"Symlink detected (rejected): {item.relative_to(skill_dir)}")
    return errors


def check_path_escape(skill_dir: Path) -> List[str]:
    """Ensure no file paths escape out of the skill directory"""
    errors = []
    skill_dir_resolved = skill_dir.resolve()
    for item in skill_dir.rglob("*"):
        try:
            resolved = item.resolve()
            resolved.relative_to(skill_dir_resolved)
        except ValueError:
            errors.append(f"Path escape: {item} resolves to {resolved}")
        except OSError:
            errors.append(f"Path resolution failed: {item}")
    return errors


def check_file_sizes(skill_dir: Path) -> List[str]:
    """Check file size limits"""
    errors = []
    total_size = 0
    file_count = 0

    for item in skill_dir.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        if any(part in EXCLUDED_DIRS for part in item.parts):
            continue

        file_count += 1
        size = item.stat().st_size
        total_size += size

        if item.name == "SKILL.md" and size > MAX_SKILL_MD_SIZE:
            errors.append(f"SKILL.md too large: {size} bytes (limit {MAX_SKILL_MD_SIZE})")
        elif size > MAX_SINGLE_FILE_SIZE:
            errors.append(f"File too large: {item.relative_to(skill_dir)} ({size} bytes, limit {MAX_SINGLE_FILE_SIZE})")

    if total_size > MAX_SKILL_TOTAL_SIZE:
        errors.append(f"Skill total size too large: {total_size} bytes (limit {MAX_SKILL_TOTAL_SIZE})")

    if file_count > MAX_SKILL_FILES:
        errors.append(f"Too many files: {file_count} (limit {MAX_SKILL_FILES})")

    return errors


def check_blocked_extensions(skill_dir: Path) -> List[str]:
    """Check whole skill directory for blocked extensions."""
    errors = []
    for item in skill_dir.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        if any(part in EXCLUDED_DIRS for part in item.parts):
            continue
        if item.suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"Blocked file type: {item.relative_to(skill_dir)}")
    return errors


def scan_scripts(skill_dir: Path) -> Tuple[List[str], List[str]]:
    """Scan scripts/ directory for dangerous patterns"""
    errors = []
    warnings = []
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return errors, warnings

    for script_file in scripts_dir.rglob("*"):
        if not script_file.is_file() or script_file.is_symlink():
            continue

        if script_file.suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"Blocked file type: {script_file.relative_to(skill_dir)}")
            continue

        try:
            content = script_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in DANGEROUS_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    warnings.append(
                        f"Potentially dangerous pattern detected in {script_file.name}: '{pattern}'"
                    )
        except Exception:
            pass

    return errors, warnings


def check_zip_safety(zip_path: Path) -> List[str]:
    """Check safety of a .skill ZIP file"""
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

                if _is_path_traversal(info.filename):
                    errors.append(f"Path traversal in ZIP: {info.filename}")

                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    errors.append(f"Symlink in ZIP: {info.filename}")

                ext = Path(info.filename).suffix.lower()
                if ext in BLOCKED_EXTENSIONS:
                    errors.append(f"Blocked file type in ZIP: {info.filename}")

                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    errors.append(f"Single file too large in ZIP: {info.filename} ({info.file_size} bytes)")

    except zipfile.BadZipFile:
        errors.append(f"Invalid ZIP file: {zip_path}")
        return errors

    if file_count > MAX_SKILL_FILES:
        errors.append(f"Too many files in ZIP: {file_count} (limit {MAX_SKILL_FILES})")
    if total_size > MAX_SKILL_TOTAL_SIZE:
        errors.append(f"ZIP total size too large: {total_size} bytes (limit {MAX_SKILL_TOTAL_SIZE})")

    return errors


def full_security_check(skill_dir: Path) -> Tuple[List[str], List[str]]:
    """Run all security checks"""
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


# ==================== Skill validation ====================


def validate_skill(skill_dir: Path, strict: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    Comprehensively validate a skill directory.

    Checks:
    1. SKILL.md exists and starts with --- frontmatter
    2. Required fields present (name, description)
    3. Body is not empty (warning only)
    4. Security checks (symlinks, path escape, script scanning)
    5. Directory name matches frontmatter name

    Args:
        skill_dir: Skill directory path
        strict: If True, warnings are also treated as errors

    Returns:
        (is_valid, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append("SKILL.md does not exist")
        return False, errors, warnings

    try:
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            errors.append("SKILL.md must start with --- frontmatter delimiter")
            return False, errors, warnings

        parts = content.split("---", 2)
        if len(parts) < 3:
            errors.append("SKILL.md missing closing --- delimiter")
            return False, errors, warnings

        yaml_str = parts[1].strip()
        if not yaml_str:
            errors.append("Frontmatter is empty")
            return False, errors, warnings

        body = parts[2].strip() if len(parts) >= 3 else ""

        yaml_data = yaml.safe_load(yaml_str)
        if not isinstance(yaml_data, dict):
            errors.append("Frontmatter must be a YAML mapping")
            return False, errors, warnings

        # Validate via Pydantic model
        from .models import SkillFrontmatter
        frontmatter = SkillFrontmatter(**yaml_data)

        if not frontmatter.description:
            warnings.append("SKILL.md frontmatter missing 'description' field")

        if skill_dir.name != frontmatter.name:
            errors.append(
                f"Directory name '{skill_dir.name}' does not match frontmatter name '{frontmatter.name}'"
            )

        if not body:
            warnings.append("SKILL.md body is empty (no instruction content)")

    except yaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        return False, errors, warnings
    except Exception as e:
        errors.append(f"Frontmatter validation error: {e}")
        return False, errors, warnings

    # Security checks
    sec_errors, sec_warnings = full_security_check(skill_dir)
    errors.extend(sec_errors)
    warnings.extend(sec_warnings)

    is_valid = len(errors) == 0
    if strict and warnings:
        is_valid = False

    return is_valid, errors, warnings
