"""
Skills Manager Module

Responsible for scanning skills directories and parsing SKILL.md files
following the Agent Skills standard (https://agentskills.io/specification).
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional

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


class SkillsManager:
    """Skills manager for discovering and parsing SKILL.md files"""

    def __init__(self, skills_dir: Optional[Path] = None):
        if skills_dir is None:
            self.skills_dir = Path.home() / ".castrel" / "skills"
        else:
            self.skills_dir = Path(skills_dir)

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


_skills_manager = SkillsManager()


def get_skills_manager() -> SkillsManager:
    """Get global SkillsManager instance"""
    return _skills_manager
