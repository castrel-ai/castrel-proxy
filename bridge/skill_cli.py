"""
Skill CLI 子命令

提供 skill init, list, info, validate, package, remove, import, sync 命令。
通过 Typer sub-app 集成到主 CLI 中。
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer

from bridge.skill_manager import SkillError, get_skill_manager

logger = logging.getLogger(__name__)

skill_app = typer.Typer(
    name="skill",
    help="管理 Skills（创建、验证、打包、同步）",
    add_completion=False,
)


@skill_app.command()
def init(
    name: str = typer.Argument(..., help="Skill 名称 (lowercase-hyphen-case, 最长 64 字符)"),
    description: str = typer.Option("", "--description", "-d", help="Skill 描述"),
    directory: Optional[str] = typer.Option(None, "--dir", help="父目录 (默认: ~/.castrel/skills/)"),
):
    """
    初始化新的 Skill 骨架

    创建包含 SKILL.md 和资源目录的 Skill 模板。

    使用方法:
      castrel-bridge-cli skill init my-skill -d "我的自定义 Skill"
    """
    manager = get_skill_manager()

    try:
        skill_dir = manager.init_skill(name, description=description, directory=directory)
        typer.secho(f"✓ Skill '{name}' 已创建", fg=typer.colors.GREEN)
        typer.echo(f"  路径: {skill_dir}")
        typer.echo(f"  结构:")
        typer.echo(f"    ├── SKILL.md")
        typer.echo(f"    ├── scripts/")
        typer.echo(f"    ├── references/")
        typer.echo(f"    └── assets/")
        typer.echo(f"\n提示: 编辑 {skill_dir}/SKILL.md 添加指令内容")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command("list")
def list_skills(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细信息"),
):
    """
    列出所有本地安装的 Skills
    """
    manager = get_skill_manager()
    skill_names = manager.discover_skills()

    if not skill_names:
        typer.echo("暂无已安装的 Skills")
        typer.echo(f"Skills 目录: {manager.skills_dir}")
        typer.echo("提示: 使用 'castrel-bridge-cli skill init <name>' 创建新 Skill")
        return

    typer.secho(f"=== Skills 列表 ({len(skill_names)} 个) ===", bold=True)
    typer.echo(f"目录: {manager.skills_dir}\n")

    for name in skill_names:
        try:
            skill = manager.load_skill(name)
            desc = skill.frontmatter.description or "(无描述)"

            if verbose:
                typer.echo(f"  {name}")
                typer.echo(f"    描述: {desc}")
                typer.echo(f"    路径: {skill.skill_dir}")
                typer.echo(f"    哈希: {skill.content_hash[:12]}...")
                resources = []
                if skill.has_scripts:
                    resources.append("scripts")
                if skill.has_references:
                    resources.append("references")
                if skill.has_assets:
                    resources.append("assets")
                typer.echo(f"    资源: {', '.join(resources) if resources else '无'}")
                typer.echo()
            else:
                # 截断描述
                max_desc_len = 60
                if len(desc) > max_desc_len:
                    desc = desc[: max_desc_len - 3] + "..."
                typer.echo(f"  {name:<30} {desc}")

        except Exception as e:
            typer.secho(f"  {name:<30} (加载失败: {e})", fg=typer.colors.YELLOW)


@skill_app.command()
def info(
    name: str = typer.Argument(..., help="Skill 名称"),
):
    """
    显示指定 Skill 的详细信息
    """
    manager = get_skill_manager()

    try:
        skill = manager.load_skill(name)
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"=== Skill: {name} ===", bold=True)
    typer.echo(f"名称: {skill.frontmatter.name}")
    typer.echo(f"描述: {skill.frontmatter.description or '(无描述)'}")
    typer.echo(f"路径: {skill.skill_dir}")
    typer.echo(f"内容哈希: {skill.content_hash}")
    typer.echo(f"更新时间: {skill.updated_at}")

    # 资源
    typer.echo(f"\n资源目录:")
    typer.echo(f"  scripts:    {'✓ (有内容)' if skill.has_scripts else '✗ (空)'}")
    typer.echo(f"  references: {'✓ (有内容)' if skill.has_references else '✗ (空)'}")
    typer.echo(f"  assets:     {'✓ (有内容)' if skill.has_assets else '✗ (空)'}")

    # Metadata
    if skill.frontmatter.metadata:
        meta = skill.frontmatter.metadata
        typer.echo(f"\n元数据:")
        if meta.emoji:
            typer.echo(f"  emoji: {meta.emoji}")
        if meta.primaryEnv:
            typer.echo(f"  primaryEnv: {meta.primaryEnv}")
        if meta.homepage:
            typer.echo(f"  homepage: {meta.homepage}")
        if meta.os:
            typer.echo(f"  os: {', '.join(meta.os)}")
        if meta.requires:
            req = meta.requires
            if req.bins:
                typer.echo(f"  requires.bins: {', '.join(req.bins)}")
            if req.anyBins:
                typer.echo(f"  requires.anyBins: {', '.join(req.anyBins)}")
            if req.env:
                typer.echo(f"  requires.env: {', '.join(req.env)}")

    # Body 预览
    if skill.body:
        preview_lines = skill.body.split("\n")[:5]
        typer.echo(f"\n指令预览:")
        for line in preview_lines:
            typer.echo(f"  {line}")
        if len(skill.body.split("\n")) > 5:
            typer.echo(f"  ... (共 {len(skill.body.split(chr(10)))} 行)")


@skill_app.command()
def validate(
    name: Optional[str] = typer.Argument(None, help="Skill 名称（省略则验证全部）"),
    strict: bool = typer.Option(False, "--strict", help="严格模式：warnings 也视为错误"),
):
    """
    验证 Skill(s) 是否符合标准
    """
    manager = get_skill_manager()

    if name:
        names = [name]
    else:
        names = manager.discover_skills()
        if not names:
            typer.echo("暂无已安装的 Skills")
            return

    all_passed = True
    for skill_name in names:
        is_valid, errors, warnings = manager.validate(skill_name, strict=strict)

        if is_valid:
            typer.secho(f"✓ {skill_name}: 验证通过", fg=typer.colors.GREEN)
        else:
            typer.secho(f"✗ {skill_name}: 验证失败", fg=typer.colors.RED)
            all_passed = False

        for error in errors:
            typer.secho(f"    错误: {error}", fg=typer.colors.RED)
        for warning in warnings:
            typer.secho(f"    警告: {warning}", fg=typer.colors.YELLOW)

    if not all_passed:
        raise typer.Exit(1)


@skill_app.command()
def package(
    name: str = typer.Argument(..., help="要打包的 Skill 名称"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出 .skill 文件路径"),
):
    """
    将 Skill 打包为 .skill ZIP 文件
    """
    manager = get_skill_manager()

    try:
        output_path = Path(output) if output else None
        result_path = manager.package_skill(name, output_path=output_path)
        size = result_path.stat().st_size
        typer.secho(f"✓ Skill '{name}' 已打包", fg=typer.colors.GREEN)
        typer.echo(f"  输出: {result_path}")
        typer.echo(f"  大小: {size:,} 字节")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command()
def remove(
    name: str = typer.Argument(..., help="要删除的 Skill 名称"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
):
    """
    删除本地安装的 Skill
    """
    manager = get_skill_manager()

    skill_dir = manager._get_skill_dir(name)
    if not skill_dir.exists():
        typer.secho(f"✗ Skill 不存在: {name}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not force:
        typer.echo(f"即将删除 Skill: {name}")
        typer.echo(f"路径: {skill_dir}")
        confirm = typer.confirm("确认删除？")
        if not confirm:
            typer.echo("已取消")
            return

    try:
        manager.remove_skill(name)
        typer.secho(f"✓ Skill '{name}' 已删除", fg=typer.colors.GREEN)
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command("import")
def import_skill(
    path: str = typer.Argument(..., help=".skill 文件或 Skill 目录路径"),
):
    """
    从 .skill ZIP 文件或目录导入 Skill
    """
    manager = get_skill_manager()

    source_path = Path(path).resolve()
    if not source_path.exists():
        typer.secho(f"✗ 路径不存在: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        name = manager.import_skill(source_path)
        typer.secho(f"✓ Skill '{name}' 已导入", fg=typer.colors.GREEN)
        typer.echo(f"  路径: {manager._get_skill_dir(name)}")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command()
def sync():
    """
    与服务端双向同步 Skills

    同步流程：
    1. 加载本地 Skills 清单
    2. 连接服务端并发送 capabilities_sync
    3. 接收服务端推送的 Skills
    4. 推送本地变更到服务端
    """
    from bridge.api import APIError, NetworkError, get_api_client
    from bridge.config import ConfigError, get_config
    from bridge.skill_sync import SkillSyncManager

    config = get_config()

    try:
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]
    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("提示: 请先使用 'castrel-bridge-cli pair' 命令进行配对", err=True)
        raise typer.Exit(1)

    typer.secho("=== Skills 同步 ===", bold=True)
    typer.echo(f"服务端: {server_url}")
    typer.echo(f"客户端ID: {client_id}")

    manager = get_skill_manager()
    sync_manager = SkillSyncManager(skill_manager=manager)

    async def do_sync():
        # 构建 Skills 注册信息
        skills_payload = manager.get_skills_for_registration()
        skill_count = len(skills_payload)

        typer.echo(f"\n本地 Skills: {skill_count} 个")
        for name in skills_payload:
            typer.echo(f"  - {name}")

        # 通过 API 同步
        api_client = get_api_client()
        typer.echo("\n正在同步到服务端...")

        from bridge.mcp_manager import get_mcp_manager

        mcp_manager = get_mcp_manager()
        tools_payload = {}

        try:
            count = await mcp_manager.connect_all()
            if count > 0:
                tools_payload = await mcp_manager.get_all_tools()
        except Exception:
            pass
        finally:
            try:
                await mcp_manager.disconnect_all()
            except Exception:
                pass

        await api_client._send_client_info(
            server_url, client_id, verification_code, workspace_id,
            tools_payload, skills=skills_payload,
        )
        typer.secho(f"✓ 已同步 {skill_count} 个 Skills 到服务端", fg=typer.colors.GREEN)

    try:
        asyncio.run(do_sync())
    except (NetworkError, APIError) as e:
        typer.secho(f"✗ 同步失败: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ 未知错误: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
