"""
Skill 数据模型

定义 SKILL.md frontmatter 和 skill 元数据的 Pydantic 模型，
完全兼容 openclaw SKILL.md 格式。
"""

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class InstallKind(str, Enum):
    """安装方式枚举"""

    BREW = "brew"
    NODE = "node"
    GO = "go"
    UV = "uv"
    DOWNLOAD = "download"


class InstallSpec(BaseModel):
    """单个安装步骤"""

    id: str = Field(..., description="唯一步骤标识")
    kind: InstallKind = Field(..., description="安装方式")
    label: str = Field("", description="人类可读标签")
    bins: List[str] = Field(default_factory=list, description="此步骤提供的可执行文件")
    os: List[str] = Field(default_factory=list, description="支持的操作系统")
    # brew 专属
    formula: Optional[str] = Field(None, description="brew formula 名称")
    # node 专属
    package: Optional[str] = Field(None, description="npm 包名")
    # go 专属
    module: Optional[str] = Field(None, description="go module 路径")
    # download 专属
    url: Optional[str] = Field(None, description="下载 URL")
    archive: Optional[str] = Field(None, description="归档文件格式")
    extract: Optional[bool] = Field(None, description="是否需要解压")
    stripComponents: Optional[int] = Field(None, description="解压时去除的路径层级")
    targetDir: Optional[str] = Field(None, description="解压目标目录")


class SkillRequirements(BaseModel):
    """Skill 运行时依赖"""

    bins: List[str] = Field(default_factory=list, description="必需的可执行文件（全部必须存在）")
    anyBins: List[str] = Field(default_factory=list, description="至少一个必须存在的可执行文件")
    env: List[str] = Field(default_factory=list, description="必需的环境变量")
    config: List[str] = Field(default_factory=list, description="必需的配置路径")


class SkillMetadata(BaseModel):
    """YAML frontmatter 中的 metadata 块"""

    emoji: str = Field("", max_length=8)
    skillKey: Optional[str] = Field(None, description="自定义配置查找键")
    primaryEnv: Optional[str] = Field(None, description="主要环境变量名称")
    homepage: Optional[str] = Field(None, description="文档链接")
    always: bool = Field(False, description="是否始终激活")
    os: List[str] = Field(default_factory=list, description="支持的操作系统: darwin, linux, windows")
    requires: Optional[SkillRequirements] = None
    install: List[InstallSpec] = Field(default_factory=list)


# Skill 名称验证正则
SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH = 64
SKILL_DESCRIPTION_MAX_LENGTH = 1024


class SkillFrontmatter(BaseModel):
    """SKILL.md 的完整 YAML frontmatter"""

    name: str = Field(..., min_length=1, max_length=SKILL_NAME_MAX_LENGTH, description="Skill 名称 (lowercase-hyphen-case)")
    description: str = Field("", max_length=SKILL_DESCRIPTION_MAX_LENGTH, description="用途和使用场景")
    metadata: Optional[SkillMetadata] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not SKILL_NAME_PATTERN.match(v):
            raise ValueError(f"Skill 名称必须为 lowercase-hyphen-case 格式: '{v}'")
        if len(v) > SKILL_NAME_MAX_LENGTH:
            raise ValueError(f"Skill 名称超过 {SKILL_NAME_MAX_LENGTH} 字符: '{v}'")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if "<" in v or ">" in v:
            raise ValueError("Skill 描述不允许包含尖括号")
        return v


class Skill(BaseModel):
    """加载到内存中的 Skill 完整表示"""

    frontmatter: SkillFrontmatter
    body: str = Field("", description="Markdown 指令内容（frontmatter 之后的部分）")
    skill_dir: str = Field(..., description="Skill 目录的绝对路径")
    has_scripts: bool = False
    has_references: bool = False
    has_assets: bool = False
    content_hash: str = Field("", description="SKILL.md 内容的 SHA256 哈希")
    updated_at: int = Field(0, description="SKILL.md 最后修改时间戳（毫秒）")


class SkillSyncEntry(BaseModel):
    """同步清单中的单条记录"""

    name: str
    content_hash: str
    updated_at: int
    description: str = ""


class SkillSyncManifest(BaseModel):
    """同步清单：所有本地 skills 的哈希信息"""

    skills: Dict[str, SkillSyncEntry] = Field(default_factory=dict)
    manifest_hash: str = Field("", description="所有 skill 哈希的组合哈希")
