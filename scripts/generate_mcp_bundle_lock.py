#!/usr/bin/env python3
"""Generate a build-time MCP bundle lock file from mcp-bundle.yaml.

The script rewrites each `prewarm:` command to pin runtime dependency versions.
- `npx` commands: resolve package versions from npm registry
- `uvx` commands: resolve package versions from PyPI

If a package version cannot be resolved, the original command is kept.
Use --strict-latest to fail fast when any npx/uvx prewarm command remains unpinned.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PREWARM_PATTERN = re.compile(r"^(\s*prewarm:\s*)(.+?)\s*$")
SHELL_SUFFIX_PATTERN = re.compile(r"\s(?:\|\||&&|\||[0-9]*>+|<)")

NPM_SCOPED_WITH_VERSION = re.compile(r"^(@[^/\s]+/[^@\s]+)@([^@\s]+)$")
NPM_UNSCOPED_WITH_VERSION = re.compile(r"^([^@\s]+)@([^@\s]+)$")
PYPI_WITH_VERSION = re.compile(r"^([A-Za-z0-9_.-]+)==([^=\s]+)$")


class Resolver:
    def __init__(self) -> None:
        self._npm_cache: dict[str, str] = {}
        self._pypi_cache: dict[str, str] = {}

    def npm_latest(self, package: str) -> str | None:
        if package in self._npm_cache:
            return self._npm_cache[package]
        try:
            result = subprocess.run(
                ["npm", "view", package, "version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None
        version = result.stdout.strip()
        if not version:
            return None
        self._npm_cache[package] = version
        return version

    def pypi_latest(self, package: str) -> str | None:
        if package in self._pypi_cache:
            return self._pypi_cache[package]
        try:
            with urlopen(f"https://pypi.org/pypi/{package}/json", timeout=20) as response:
                payload = json.load(response)
        except (URLError, TimeoutError, json.JSONDecodeError):
            return None
        info = payload.get("info", {})
        version = info.get("version")
        if not version or not isinstance(version, str):
            return None
        self._pypi_cache[package] = version
        return version


def split_npm_package(spec: str) -> tuple[str, str | None]:
    scoped = NPM_SCOPED_WITH_VERSION.match(spec)
    if scoped:
        return scoped.group(1), scoped.group(2)
    unscoped = NPM_UNSCOPED_WITH_VERSION.match(spec)
    if unscoped:
        return unscoped.group(1), unscoped.group(2)
    return spec, None


def split_pypi_package(spec: str) -> tuple[str, str | None]:
    matched = PYPI_WITH_VERSION.match(spec)
    if matched:
        return matched.group(1), matched.group(2)
    return spec, None


def split_shell_suffix(command: str) -> tuple[str, str]:
    """Split shell command into executable base and shell suffix.

    Keep suffix operators (redirects/pipes/boolean ops) unchanged so the generated
    lock command remains executable in `sh -lc`.
    """
    matched = SHELL_SUFFIX_PATTERN.search(command)
    if not matched:
        return command.strip(), ""
    index = matched.start()
    return command[:index].rstrip(), command[index:]


def resolve_npx_command(command: str, resolver: Resolver) -> str:
    base_command, suffix = split_shell_suffix(command)
    try:
        tokens = shlex.split(base_command)
    except ValueError:
        return command
    if len(tokens) < 2 or tokens[0] != "npx":
        return command

    pkg_index: int | None = None
    for i in range(1, len(tokens)):
        token = tokens[i]
        if token.startswith("-"):
            continue
        pkg_index = i
        break
    if pkg_index is None:
        return command

    package, version = split_npm_package(tokens[pkg_index])
    if version and version != "latest":
        return command

    latest = resolver.npm_latest(package)
    if not latest:
        return command

    tokens[pkg_index] = f"{package}@{latest}"
    rebuilt = " ".join(tokens)
    return f"{rebuilt}{suffix}".rstrip()


def resolve_uvx_command(command: str, resolver: Resolver) -> str:
    base_command, suffix = split_shell_suffix(command)
    try:
        tokens = shlex.split(base_command)
    except ValueError:
        return command
    if len(tokens) < 2 or tokens[0] != "uvx":
        return command

    if "--from" in tokens:
        from_index = tokens.index("--from")
        if from_index + 1 >= len(tokens):
            return command
        source_spec = tokens[from_index + 1]
        package, version = split_pypi_package(source_spec)
        if version:
            return command
        latest = resolver.pypi_latest(package)
        if not latest:
            return command
        tokens[from_index + 1] = f"{package}=={latest}"
        rebuilt = " ".join(tokens)
        return f"{rebuilt}{suffix}".rstrip()

    cmd_index: int | None = None
    for i in range(1, len(tokens)):
        token = tokens[i]
        if token.startswith("-"):
            continue
        cmd_index = i
        break
    if cmd_index is None:
        return command

    package, version = split_pypi_package(tokens[cmd_index])
    if version:
        return command

    latest = resolver.pypi_latest(package)
    if not latest:
        return command

    command_name = tokens[cmd_index]
    rebuilt = ["uvx", "--from", f"{package}=={latest}", command_name, *tokens[cmd_index + 1 :]]
    return f"{' '.join(rebuilt)}{suffix}".rstrip()


def resolve_prewarm(command: str, resolver: Resolver) -> str:
    stripped = command.strip()
    if stripped in {"true", "false"}:
        return command
    if stripped.startswith("npx "):
        return resolve_npx_command(stripped, resolver)
    if stripped.startswith("uvx "):
        return resolve_uvx_command(stripped, resolver)
    return command


def is_npx_pinned(command: str) -> bool:
    base_command, _ = split_shell_suffix(command)
    try:
        tokens = shlex.split(base_command)
    except ValueError:
        return False
    if len(tokens) < 2 or tokens[0] != "npx":
        return True

    pkg_index: int | None = None
    for i in range(1, len(tokens)):
        token = tokens[i]
        if token.startswith("-"):
            continue
        pkg_index = i
        break
    if pkg_index is None:
        return False

    _, version = split_npm_package(tokens[pkg_index])
    return bool(version and version != "latest")


def is_uvx_pinned(command: str) -> bool:
    base_command, _ = split_shell_suffix(command)
    try:
        tokens = shlex.split(base_command)
    except ValueError:
        return False
    if len(tokens) < 2 or tokens[0] != "uvx":
        return True

    if "--from" not in tokens:
        return False
    from_index = tokens.index("--from")
    if from_index + 1 >= len(tokens):
        return False

    _, version = split_pypi_package(tokens[from_index + 1])
    return bool(version)


def is_prewarm_pinned(command: str) -> bool:
    stripped = command.strip()
    if stripped in {"true", "false"}:
        return True
    if stripped.startswith("npx "):
        return is_npx_pinned(stripped)
    if stripped.startswith("uvx "):
        return is_uvx_pinned(stripped)
    return True


def generate_lock(input_path: Path, output_path: Path, strict_latest: bool = False) -> int:
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    resolver = Resolver()
    output_lines: list[str] = []
    unresolved: list[tuple[int, str]] = []

    for line_no, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        matched = PREWARM_PATTERN.match(raw_line)
        if not matched:
            output_lines.append(raw_line)
            continue

        prefix = matched.group(1)
        command = matched.group(2)
        locked = resolve_prewarm(command, resolver)
        if strict_latest and not is_prewarm_pinned(locked):
            unresolved.append((line_no, locked))
        output_lines.append(f"{prefix}{locked}")

    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    if strict_latest and unresolved:
        print("Unpinned prewarm commands detected in strict mode:", file=sys.stderr)
        for line_no, cmd in unresolved:
            print(f"  line {line_no}: {cmd}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate mcp-bundle.lock.yaml from mcp-bundle.yaml")
    parser.add_argument("--input", default="mcp-bundle.yaml", help="Path to source mcp-bundle yaml")
    parser.add_argument("--output", default="mcp-bundle.lock.yaml", help="Path to generated lock yaml")
    parser.add_argument(
        "--strict-latest",
        action="store_true",
        help="Fail when any npx/uvx prewarm command remains unpinned after resolution",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return generate_lock(Path(args.input), Path(args.output), strict_latest=args.strict_latest)


if __name__ == "__main__":
    raise SystemExit(main())
