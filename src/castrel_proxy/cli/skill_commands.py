"""
Skill CLI Subcommands

Provides skill init, list, info, validate, package, remove, import, sync commands.
Integrated into the main CLI via a Typer sub-app.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer

from ..skills.manager import SkillError, get_skills_manager

logger = logging.getLogger(__name__)

skill_app = typer.Typer(
    name="skill",
    help="Manage Skills (create, validate, package, sync)",
    add_completion=False,
)


@skill_app.command()
def init(
    name: str = typer.Argument(..., help="Skill name (lowercase-hyphen-case, max 64 chars)"),
    description: str = typer.Option("", "--description", "-d", help="Skill description"),
    directory: Optional[str] = typer.Option(None, "--dir", help="Parent directory (default: ~/.castrel/skills/)"),
):
    """
    Initialize a new Skill skeleton.

    Creates a Skill template with SKILL.md and resource directories.

    Usage:
      castrel-proxy skill init my-skill -d "My custom skill"
    """
    manager = get_skills_manager()

    try:
        skill_dir = manager.init_skill(name, description=description, directory=directory)
        typer.secho(f"✓ Skill '{name}' created", fg=typer.colors.GREEN)
        typer.echo(f"  Path: {skill_dir}")
        typer.echo("  Structure:")
        typer.echo("    ├── SKILL.md")
        typer.echo("    ├── scripts/")
        typer.echo("    ├── references/")
        typer.echo("    └── assets/")
        typer.echo(f"\nHint: Edit {skill_dir}/SKILL.md to add instructions")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command("list")
def list_skills(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed information"),
):
    """
    List all locally installed Skills.
    """
    manager = get_skills_manager()
    skill_names = manager.discover_skills()

    if not skill_names:
        typer.echo("No skills installed")
        typer.echo(f"Skills directory: {manager.skills_dir}")
        typer.echo("Hint: Use 'castrel-proxy skill init <name>' to create a new skill")
        return

    typer.secho(f"=== Skills ({len(skill_names)}) ===", bold=True)
    typer.echo(f"Directory: {manager.skills_dir}\n")

    for name in skill_names:
        try:
            skill = manager.load_skill(name)
            desc = skill.frontmatter.description or "(no description)"

            if verbose:
                typer.echo(f"  {name}")
                typer.echo(f"    Description: {desc}")
                typer.echo(f"    Path:        {skill.skill_dir}")
                typer.echo(f"    Hash:        {skill.content_hash[:12]}...")
                resources = []
                if skill.has_scripts:
                    resources.append("scripts")
                if skill.has_references:
                    resources.append("references")
                if skill.has_assets:
                    resources.append("assets")
                typer.echo(f"    Resources:   {', '.join(resources) if resources else 'none'}")
                typer.echo()
            else:
                max_desc_len = 60
                if len(desc) > max_desc_len:
                    desc = desc[: max_desc_len - 3] + "..."
                typer.echo(f"  {name:<30} {desc}")

        except Exception as e:
            typer.secho(f"  {name:<30} (load failed: {e})", fg=typer.colors.YELLOW)


@skill_app.command()
def info(
    name: str = typer.Argument(..., help="Skill name"),
):
    """
    Show detailed information for a specific Skill.
    """
    manager = get_skills_manager()

    try:
        skill = manager.load_skill(name)
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"=== Skill: {name} ===", bold=True)
    typer.echo(f"Name:         {skill.frontmatter.name}")
    typer.echo(f"Description:  {skill.frontmatter.description or '(no description)'}")
    typer.echo(f"Path:         {skill.skill_dir}")
    typer.echo(f"Content hash: {skill.content_hash}")
    typer.echo(f"Updated at:   {skill.updated_at}")

    typer.echo("\nResource directories:")
    typer.echo(f"  scripts:    {'✓ (has content)' if skill.has_scripts else '✗ (empty)'}")
    typer.echo(f"  references: {'✓ (has content)' if skill.has_references else '✗ (empty)'}")
    typer.echo(f"  assets:     {'✓ (has content)' if skill.has_assets else '✗ (empty)'}")

    # Try to display rich frontmatter metadata using Pydantic models
    try:
        import yaml

        from ..skills.models import SkillFrontmatter

        skill_dir = Path(skill.skill_dir)
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) >= 3:
            yaml_data = yaml.safe_load(parts[1].strip()) or {}
            fm = SkillFrontmatter(**yaml_data)

            if fm.metadata:
                meta = fm.metadata
                typer.echo("\nMetadata:")
                if meta.emoji:
                    typer.echo(f"  emoji:      {meta.emoji}")
                if meta.primaryEnv:
                    typer.echo(f"  primaryEnv: {meta.primaryEnv}")
                if meta.homepage:
                    typer.echo(f"  homepage:   {meta.homepage}")
                if meta.os:
                    typer.echo(f"  os:         {', '.join(meta.os)}")
                if meta.requires:
                    req = meta.requires
                    if req.bins:
                        typer.echo(f"  requires.bins:    {', '.join(req.bins)}")
                    if req.anyBins:
                        typer.echo(f"  requires.anyBins: {', '.join(req.anyBins)}")
                    if req.env:
                        typer.echo(f"  requires.env:     {', '.join(req.env)}")
    except Exception:
        pass  # Metadata display is best-effort; basic info already shown above

    if skill.body:
        preview_lines = skill.body.split("\n")[:5]
        typer.echo("\nInstruction preview:")
        for line in preview_lines:
            typer.echo(f"  {line}")
        total_lines = len(skill.body.split("\n"))
        if total_lines > 5:
            typer.echo(f"  ... ({total_lines} lines total)")


@skill_app.command()
def validate(
    name: Optional[str] = typer.Argument(None, help="Skill name (omit to validate all)"),
    strict: bool = typer.Option(False, "--strict", help="Strict mode: treat warnings as errors"),
):
    """
    Validate one or all Skills against the standard.
    """
    manager = get_skills_manager()

    if name:
        names = [name]
    else:
        names = manager.discover_skills()
        if not names:
            typer.echo("No skills installed")
            return

    all_passed = True
    for skill_name in names:
        is_valid, errors, warnings = manager.validate(skill_name, strict=strict)

        if is_valid:
            typer.secho(f"✓ {skill_name}: passed", fg=typer.colors.GREEN)
        else:
            typer.secho(f"✗ {skill_name}: failed", fg=typer.colors.RED)
            all_passed = False

        for error in errors:
            typer.secho(f"    error: {error}", fg=typer.colors.RED)
        for warning in warnings:
            typer.secho(f"    warning: {warning}", fg=typer.colors.YELLOW)

    if not all_passed:
        raise typer.Exit(1)


@skill_app.command()
def package(
    name: str = typer.Argument(..., help="Name of the skill to package"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output .skill file path"),
):
    """
    Package a Skill into a .skill ZIP file.
    """
    manager = get_skills_manager()

    try:
        output_path = Path(output) if output else None
        result_path = manager.package_skill(name, output_path=output_path)
        size = result_path.stat().st_size
        typer.secho(f"✓ Skill '{name}' packaged", fg=typer.colors.GREEN)
        typer.echo(f"  Output: {result_path}")
        typer.echo(f"  Size:   {size:,} bytes")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command()
def remove(
    name: str = typer.Argument(..., help="Name of the skill to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a locally installed Skill.
    """
    manager = get_skills_manager()

    skill_dir = manager._get_skill_dir(name)
    if not skill_dir.exists():
        typer.secho(f"✗ Skill not found: {name}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not force:
        typer.echo(f"About to delete skill: {name}")
        typer.echo(f"Path: {skill_dir}")
        confirm = typer.confirm("Confirm deletion?")
        if not confirm:
            typer.echo("Cancelled")
            return

    try:
        manager.remove_skill(name)
        typer.secho(f"✓ Skill '{name}' deleted", fg=typer.colors.GREEN)
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command("import")
def import_skill(
    path: str = typer.Argument(..., help=".skill file path or skill directory"),
):
    """
    Import a Skill from a .skill ZIP file or directory.
    """
    manager = get_skills_manager()

    source_path = Path(path).resolve()
    if not source_path.exists():
        typer.secho(f"✗ Path not found: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        name = manager.import_skill(source_path)
        typer.secho(f"✓ Skill '{name}' imported", fg=typer.colors.GREEN)
        typer.echo(f"  Path: {manager._get_skill_dir(name)}")
    except SkillError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@skill_app.command()
def sync():
    """
    Synchronize skills with the server.

    Sync flow:
    1. Load local skills manifest
    2. Connect to server and send capabilities_sync
    3. Receive skills pushed by the server
    4. Push local changes to the server
    """
    from ..core.config import ConfigError, get_config
    from ..network.api_client import APIError, NetworkError, get_api_client

    config = get_config()

    try:
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]
    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("Hint: Please pair first using 'castrel-proxy pair' command", err=True)
        raise typer.Exit(1)

    typer.secho("=== Skills Sync ===", bold=True)
    typer.echo(f"Server:    {server_url}")
    typer.echo(f"Client ID: {client_id}")

    manager = get_skills_manager()
    api_client = get_api_client()

    async def do_sync():
        skills_payload = manager.get_skills_for_registration()
        skill_count = len(skills_payload)

        typer.echo(f"\nLocal skills: {skill_count}")
        for skill_name in skills_payload:
            typer.echo(f"  - {skill_name}")

        from ..mcp.manager import get_mcp_manager

        mcp_manager = get_mcp_manager()
        tools_payload: dict = {}

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

        typer.echo("\nSending to server...")
        await api_client._send_client_info(
            server_url, client_id, verification_code, workspace_id,
            tools_payload, skills=skills_payload,
        )
        typer.secho(f"✓ Synced {skill_count} skill(s) to server", fg=typer.colors.GREEN)

    try:
        asyncio.run(do_sync())
    except (NetworkError, APIError) as e:
        typer.secho(f"✗ Sync failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ Unknown error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
