"""
Skills Manager Module

Responsible for scanning skills directories and parsing SKILL.md files
following the Agent Skills standard (https://agentskills.io/specification).
"""

import hashlib
import json
import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import SkillSyncEntry, SkillSyncManifest

logger = logging.getLogger(__name__)

# YAML frontmatter regex: matches content between --- delimiters at file start
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Simple YAML key-value parser for frontmatter fields we care about
_YAML_KV_RE = re.compile(r"^(\w[\w-]*):\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(content: str) -> Dict[str, str]:
    """
    Parse YAML frontmatter from SKILL.md content.
    Uses simple regex instead of a full YAML parser to avoid extra dependencies.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    frontmatter_text = match.group(1)
    result = {}
    for kv_match in _YAML_KV_RE.finditer(frontmatter_text):
        key = kv_match.group(1)
        value = kv_match.group(2).strip().strip('"').strip("'")
        result[key] = value

    return result


@dataclass
class SkillFrontmatterData:
    """Lightweight frontmatter representation parsed from SKILL.md"""
    name: str
    description: str = ""


@dataclass
class SkillData:
    """Full skill data loaded into memory"""
    frontmatter: SkillFrontmatterData
    body: str
    skill_dir: str
    content_hash: str
    updated_at: int
    has_scripts: bool = False
    has_references: bool = False
    has_assets: bool = False


class SkillError(Exception):
    """Skill-related errors"""
    pass


# SKILL.md template for new skills
_SKILL_MD_TEMPLATE = """---
name: {name}
description: "{description}"
---

# {display_name}

<!-- Write skill instructions here -->
"""


class SkillsManager:
    """Skills manager for discovering and parsing SKILL.md files"""

    def __init__(self, skills_dir: Optional[Path] = None):
        if skills_dir is None:
            self.skills_dir = Path.home() / ".castrel" / "skills"
        else:
            self.skills_dir = Path(skills_dir).expanduser()

    def scan_skills(self) -> Dict[str, Dict]:
        """
        Scan the skills directory and parse all valid SKILL.md files.

        Returns:
            Dict mapping skill name to metadata dict with keys:
            description, skill_path, has_scripts, has_references, has_assets, updated_at
        """
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            logger.debug(f"Skills directory does not exist: {self.skills_dir}")
            return {}

        skills = {}

        try:
            for entry in sorted(self.skills_dir.iterdir()):
                if not entry.is_dir():
                    continue

                skill_md = entry / "SKILL.md"
                if not skill_md.exists():
                    logger.debug(f"Skipping directory without SKILL.md: {entry.name}")
                    continue

                skill_info = self._parse_skill(entry, skill_md)
                if skill_info:
                    name = skill_info["name"]
                    skills[name] = skill_info

        except PermissionError as e:
            logger.error(f"Permission denied scanning skills directory: {e}")
        except Exception as e:
            logger.error(f"Error scanning skills directory: {e}")

        logger.info(f"Discovered {len(skills)} skill(s) in {self.skills_dir}")
        return skills

    def _parse_skill(self, skill_dir: Path, skill_md: Path) -> Optional[Dict]:
        """Parse a single skill directory"""
        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read {skill_md}: {e}")
            return None

        frontmatter = _parse_frontmatter(content)

        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")

        if not name:
            logger.warning(f"SKILL.md missing 'name' field: {skill_md}")
            return None

        file_stat = skill_md.stat()
        updated_at = int(file_stat.st_mtime * 1000)

        return {
            "name": name,
            "description": description,
            "skill_path": str(skill_dir.resolve()),
            "has_scripts": (skill_dir / "scripts").is_dir(),
            "has_references": (skill_dir / "references").is_dir(),
            "has_assets": (skill_dir / "assets").is_dir(),
            "updated_at": updated_at,
        }

    def get_skills_hash(self, skills: Dict[str, Dict]) -> str:
        """
        Compute a stable hash for the skills dict to detect changes.
        """
        if not skills:
            return ""

        hash_input = json.dumps(skills, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

    # ==================== Sync support methods ====================

    def _ensure_skills_dir(self) -> None:
        """Ensure ~/.castrel/skills/ directory exists"""
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _get_skill_dir(self, name: str) -> Path:
        """Get absolute path to a skill directory"""
        return self.skills_dir / name

    def _parse_skill_md(self, skill_md_path: Path) -> Tuple["SkillFrontmatterData", str]:
        """
        Parse SKILL.md into frontmatter and body using yaml.safe_load.

        Returns:
            (SkillFrontmatterData, body_markdown)

        Raises:
            SkillError: If SKILL.md cannot be parsed or is missing required fields
        """
        import yaml

        content = skill_md_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            raise SkillError(f"SKILL.md must start with ---: {skill_md_path}")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise SkillError(f"SKILL.md missing closing --- delimiter: {skill_md_path}")

        yaml_str = parts[1].strip()
        body = parts[2].strip()

        try:
            yaml_data = yaml.safe_load(yaml_str) or {}
        except yaml.YAMLError as e:
            raise SkillError(f"YAML parse error in {skill_md_path}: {e}")

        if not isinstance(yaml_data, dict):
            raise SkillError(f"Frontmatter must be a YAML mapping: {skill_md_path}")

        name = str(yaml_data.get("name", "")).strip()
        description = str(yaml_data.get("description", "")).strip()

        if not name:
            raise SkillError(f"SKILL.md missing 'name' field: {skill_md_path}")

        return SkillFrontmatterData(name=name, description=description), body

    def load_skill(self, name: str) -> SkillData:
        """
        Load a skill by name.

        Returns:
            SkillData with frontmatter, body, skill_dir, content_hash, updated_at

        Raises:
            SkillError: If skill does not exist or cannot be parsed
        """
        skill_dir = self._get_skill_dir(name)
        skill_md_path = skill_dir / "SKILL.md"

        if not skill_md_path.exists():
            raise SkillError(f"Skill not found: {name}")

        frontmatter, body = self._parse_skill_md(skill_md_path)

        content_bytes = skill_md_path.read_bytes()
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        updated_at = int(skill_md_path.stat().st_mtime * 1000)

        return SkillData(
            frontmatter=frontmatter,
            body=body,
            skill_dir=str(skill_dir.resolve()),
            content_hash=content_hash,
            updated_at=updated_at,
            has_scripts=(skill_dir / "scripts").is_dir(),
            has_references=(skill_dir / "references").is_dir(),
            has_assets=(skill_dir / "assets").is_dir(),
        )

    def remove_skill(self, name: str) -> None:
        """
        Delete a skill directory.

        Raises:
            SkillError: If skill does not exist
        """
        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            raise SkillError(f"Skill not found: {name}")
        shutil.rmtree(skill_dir)
        logger.info(f"Skill deleted: {name}")

    def build_sync_manifest(self) -> SkillSyncManifest:
        """
        Build sync manifest of all local skills (name, content_hash, updated_at, description).

        Returns:
            SkillSyncManifest
        """
        skills_dict: Dict[str, SkillSyncEntry] = {}
        all_hashes = []

        for entry in sorted(self.skills_dir.iterdir()) if self.skills_dir.exists() else []:
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                skill = self.load_skill(entry.name)
                sync_entry = SkillSyncEntry(
                    name=skill.frontmatter.name,
                    content_hash=skill.content_hash,
                    updated_at=skill.updated_at,
                    description=skill.frontmatter.description,
                )
                skills_dict[skill.frontmatter.name] = sync_entry
                all_hashes.append(skill.content_hash)
            except Exception as e:
                logger.warning(f"Failed to load skill '{entry.name}', skipping: {e}")

        combined = "|".join(sorted(all_hashes))
        manifest_hash = hashlib.sha256(combined.encode()).hexdigest()[:16] if all_hashes else ""

        return SkillSyncManifest(skills=skills_dict, manifest_hash=manifest_hash)

    def get_skills_for_registration(self) -> Dict[str, Dict]:
        """
        Build skills dict for capabilities_sync / server registration.

        Returns server-compatible BridgeSkillInfo format:
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
        result: Dict[str, Dict] = {}
        for name, info in self.scan_skills().items():
            result[name] = info
        return result

    # ==================== Full CRUD ====================

    def discover_skills(self) -> List[str]:
        """Return a sorted list of valid skill names found in the skills directory."""
        self._ensure_skills_dir()
        names = []
        for item in sorted(self.skills_dir.iterdir()):
            if item.is_dir() and (item / "SKILL.md").exists():
                names.append(item.name)
        return names

    def init_skill(self, name: str, description: str = "", directory: Optional[str] = None) -> Path:
        """
        Create a new skill skeleton directory.

        Structure:
          <parent>/<name>/
          ├── SKILL.md
          ├── scripts/
          ├── references/
          └── assets/

        Args:
            name: Skill name (lowercase-hyphen-case, max 64 chars)
            description: Skill description
            directory: Parent directory (defaults to skills_dir)

        Returns:
            Path to the created skill directory

        Raises:
            SkillError: Validation failure or directory already exists
        """
        from .models import SKILL_NAME_MAX_LENGTH, SKILL_NAME_PATTERN

        if not SKILL_NAME_PATTERN.match(name):
            raise SkillError(f"Skill name must be lowercase-hyphen-case: '{name}'")
        if len(name) > SKILL_NAME_MAX_LENGTH:
            raise SkillError(f"Skill name exceeds {SKILL_NAME_MAX_LENGTH} characters")

        if directory:
            parent_dir = Path(directory)
        else:
            self._ensure_skills_dir()
            parent_dir = self.skills_dir

        skill_dir = parent_dir / name
        if skill_dir.exists():
            raise SkillError(f"Skill directory already exists: {skill_dir}")

        skill_dir.mkdir(parents=True)
        (skill_dir / "scripts").mkdir()
        (skill_dir / "references").mkdir()
        (skill_dir / "assets").mkdir()

        display_name = name.replace("-", " ").title()
        skill_md_content = _SKILL_MD_TEMPLATE.format(
            name=name,
            description=description or f"{display_name} skill",
            display_name=display_name,
        )
        (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

        logger.info(f"Skill initialized: {skill_dir}")
        return skill_dir

    def validate(self, name: str, strict: bool = False) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a skill against the openclaw standard.

        Args:
            name: Skill name
            strict: If True, warnings are also treated as errors

        Returns:
            (is_valid, errors, warnings)
        """
        from .validator import validate_skill as _validate_skill

        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            return False, [f"Skill directory not found: {name}"], []
        return _validate_skill(skill_dir, strict=strict)

    def compute_content_hash(self, name: str) -> str:
        """Compute SHA256 hash of SKILL.md content for the named skill."""
        skill_md_path = self._get_skill_dir(name) / "SKILL.md"
        if not skill_md_path.exists():
            return ""
        return hashlib.sha256(skill_md_path.read_bytes()).hexdigest()

    def package_skill(self, name: str, output_path: Optional[Path] = None) -> Path:
        """
        Package a skill into a .skill ZIP file.

        Args:
            name: Skill name
            output_path: Output path (defaults to ./<name>.skill)

        Returns:
            Path to the created .skill file

        Raises:
            SkillError: Validation failure
        """
        from .validator import EXCLUDED_DIRS, full_security_check
        from .validator import validate_skill as _validate_skill

        skill_dir = self._get_skill_dir(name)
        if not skill_dir.exists():
            raise SkillError(f"Skill not found: {name}")

        is_valid, errors, _ = _validate_skill(skill_dir)
        if not is_valid:
            raise SkillError("Skill validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        sec_errors, _ = full_security_check(skill_dir)
        if sec_errors:
            raise SkillError("Security check failed:\n" + "\n".join(f"  - {e}" for e in sec_errors))

        if output_path is None:
            output_path = Path.cwd() / f"{name}.skill"
        else:
            output_path = Path(output_path)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in skill_dir.rglob("*"):
                if any(part in EXCLUDED_DIRS for part in item.parts):
                    continue
                if item.is_symlink():
                    raise SkillError(f"Refusing to package symbolic link: {item}")
                if item.is_file():
                    arcname = str(item.relative_to(skill_dir))
                    zf.write(item, arcname)

        logger.info(f"Skill packaged: {output_path}")
        return output_path

    def import_skill(self, source_path: Path) -> str:
        """
        Import a skill from a .skill ZIP file or directory.

        Args:
            source_path: Path to .skill file or skill directory

        Returns:
            Imported skill name

        Raises:
            SkillError: Import failure
        """
        source_path = Path(source_path).resolve()

        if source_path.is_file() and source_path.suffix == ".skill":
            return self._import_from_zip(source_path)
        elif source_path.is_dir():
            return self._import_from_dir(source_path)
        else:
            raise SkillError(f"Unrecognized import source: {source_path} (needs .skill file or directory)")

    # ==================== Private helpers ====================

    def _import_from_zip(self, zip_path: Path) -> str:
        """Import from a .skill ZIP file."""
        from .validator import check_zip_safety

        zip_errors = check_zip_safety(zip_path)
        if zip_errors:
            raise SkillError("ZIP safety check failed:\n" + "\n".join(f"  - {e}" for e in zip_errors))

        self._ensure_skills_dir()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_path)

            skill_md_candidates = list(tmp_path.rglob("SKILL.md"))
            if not skill_md_candidates:
                raise SkillError("SKILL.md not found in ZIP")

            skill_md = min(skill_md_candidates, key=lambda p: len(p.relative_to(tmp_path).parts))
            skill_root = skill_md.parent

            frontmatter, _ = self._parse_skill_md(skill_md)
            name = frontmatter.name

            candidate_dir = tmp_path / name
            if candidate_dir.exists():
                shutil.rmtree(candidate_dir)
            shutil.copytree(skill_root, candidate_dir)
            self._validate_import_candidate(candidate_dir)

            target_dir = self.skills_dir / name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(candidate_dir, target_dir)

        logger.info(f"Skill imported from ZIP: {name}")
        return name

    def _import_from_dir(self, source_dir: Path) -> str:
        """Import from a directory."""
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillError(f"SKILL.md not found in directory: {source_dir}")

        frontmatter, _ = self._parse_skill_md(skill_md)
        name = frontmatter.name

        self._validate_import_candidate(source_dir)
        self._ensure_skills_dir()
        target_dir = self.skills_dir / name
        if target_dir.exists():
            shutil.rmtree(target_dir)

        from .validator import EXCLUDED_DIRS
        shutil.copytree(source_dir, target_dir, ignore=shutil.ignore_patterns(*EXCLUDED_DIRS))

        logger.info(f"Skill imported from directory: {name}")
        return name

    def _validate_import_candidate(self, candidate_dir: Path) -> None:
        """Validate a candidate skill directory before importing."""
        from .validator import validate_skill as _validate_skill

        is_valid, errors, warnings = _validate_skill(candidate_dir, strict=False)
        if not is_valid:
            raise SkillError("Import content validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
        if warnings:
            logger.warning("Import content has warnings: %s", "; ".join(warnings))


_skills_manager: Optional[SkillsManager] = None


def get_skills_manager() -> SkillsManager:
    """Get a global SkillsManager using the configured host skills directory."""
    global _skills_manager
    configured_dir: Optional[Path] = None
    try:
        from ..core.config import ConfigError, get_config

        configured_dir = get_config().get_skills_directory()
    except ConfigError:
        configured_dir = None

    if _skills_manager is None or (
        configured_dir is not None and _skills_manager.skills_dir != configured_dir
    ):
        _skills_manager = SkillsManager(configured_dir)
    return _skills_manager
