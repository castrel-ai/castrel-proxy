"""
Skill Data Models

Defines Pydantic models for SKILL.md frontmatter and skill metadata,
fully compatible with the openclaw SKILL.md specification.
"""

import re
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class InstallKind(str, Enum):
    """Installation method enum"""

    BREW = "brew"
    NODE = "node"
    GO = "go"
    UV = "uv"
    DOWNLOAD = "download"


class InstallSpec(BaseModel):
    """Single installation step specification"""

    id: str = Field(..., description="Unique step identifier")
    kind: InstallKind = Field(..., description="Installation method")
    label: str = Field("", description="Human-readable label")
    bins: List[str] = Field(default_factory=list, description="Executables provided by this step")
    os: List[str] = Field(default_factory=list, description="Supported operating systems")
    # brew-specific
    formula: Optional[str] = Field(None, description="Homebrew formula name")
    # node-specific
    package: Optional[str] = Field(None, description="npm package name")
    # go-specific
    module: Optional[str] = Field(None, description="Go module path")
    # download-specific
    url: Optional[str] = Field(None, description="Download URL")
    archive: Optional[str] = Field(None, description="Archive file format")
    extract: Optional[bool] = Field(None, description="Whether extraction is required")
    stripComponents: Optional[int] = Field(None, description="Path components to strip on extraction")
    targetDir: Optional[str] = Field(None, description="Extraction target directory")


class SkillRequirements(BaseModel):
    """Skill runtime dependencies"""

    bins: List[str] = Field(default_factory=list, description="Required executables (all must exist)")
    anyBins: List[str] = Field(default_factory=list, description="At least one must exist")
    env: List[str] = Field(default_factory=list, description="Required environment variables")
    config: List[str] = Field(default_factory=list, description="Required config paths")


class SkillMetadata(BaseModel):
    """Metadata block in YAML frontmatter"""

    emoji: str = Field("", max_length=8)
    skillKey: Optional[str] = Field(None, description="Custom config lookup key")
    primaryEnv: Optional[str] = Field(None, description="Primary environment variable name")
    homepage: Optional[str] = Field(None, description="Documentation link")
    always: bool = Field(False, description="Whether skill is always active")
    os: List[str] = Field(default_factory=list, description="Supported OS: darwin, linux, windows")
    requires: Optional[SkillRequirements] = None
    install: List[InstallSpec] = Field(default_factory=list)


# Skill name validation regex
SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH = 64
SKILL_DESCRIPTION_MAX_LENGTH = 1024


class SkillFrontmatter(BaseModel):
    """Complete YAML frontmatter for SKILL.md"""

    name: str = Field(..., min_length=1, max_length=SKILL_NAME_MAX_LENGTH, description="Skill name (lowercase-hyphen-case)")
    description: str = Field("", max_length=SKILL_DESCRIPTION_MAX_LENGTH, description="Purpose and usage context")
    metadata: Optional[SkillMetadata] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not SKILL_NAME_PATTERN.match(v):
            raise ValueError(f"Skill name must be in lowercase-hyphen-case format: '{v}'")
        if len(v) > SKILL_NAME_MAX_LENGTH:
            raise ValueError(f"Skill name exceeds {SKILL_NAME_MAX_LENGTH} characters: '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if "<" in v or ">" in v:
            raise ValueError("Skill description must not contain angle brackets")
        return v


class Skill(BaseModel):
    """Complete in-memory representation of a loaded Skill"""

    frontmatter: SkillFrontmatter
    body: str = Field("", description="Markdown instruction content (after frontmatter)")
    skill_dir: str = Field(..., description="Absolute path to the skill directory")
    has_scripts: bool = False
    has_references: bool = False
    has_assets: bool = False
    content_hash: str = Field("", description="SHA256 hash of SKILL.md content")
    updated_at: int = Field(0, description="Last modification timestamp of SKILL.md (milliseconds)")


class SkillSyncEntry(BaseModel):
    """Single record in sync manifest"""

    name: str
    content_hash: str
    updated_at: int
    description: str = ""


class SkillSyncManifest(BaseModel):
    """Sync manifest: hash information for all local skills"""

    skills: Dict[str, SkillSyncEntry] = Field(default_factory=dict)
    manifest_hash: str = Field("", description="Combined hash of all skill hashes")
