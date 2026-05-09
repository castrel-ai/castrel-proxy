#!/usr/bin/env python3
"""Manually refresh backend MCP package versions without CI.

This script uses mcp-bundle template as source-of-truth and updates:
1) backend builtin MCP npx package specs for MCPs that use npx
2) strict validation for resolvable prewarm commands

It does NOT modify generated bundle artifacts in Git.

Usage:
    python3 scripts/refresh_mcp_versions.py
"""

from __future__ import annotations

import re
import shlex
import tempfile
import sys
from pathlib import Path

from generate_mcp_bundle_lock import PREWARM_PATTERN, Resolver, generate_lock, resolve_prewarm, split_shell_suffix

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_FILE = ROOT / "open-castrel-proxy" / "mcp-bundle.template.yaml"
BACKEND_FILE = ROOT / "backend" / "app" / "services" / "store" / "mcp" / "builtin_mcp_servers.py"


def resolve_template_and_collect_mapping(template_path: Path, resolver: Resolver) -> tuple[str, dict[str, str]]:
    """Resolve template prewarm commands and return resolved yaml + MCP->npx package mapping."""
    lines = template_path.read_text(encoding="utf-8").splitlines()
    resolved_lines: list[str] = []
    current_name: str | None = None
    mcp_to_npx_spec: dict[str, str] = {}

    for raw_line in lines:
        name_match = re.match(r"^\s*-\s*name:\s*([A-Za-z0-9_\-]+)\s*$", raw_line)
        if name_match:
            current_name = name_match.group(1)
            resolved_lines.append(raw_line)
            continue

        prewarm_match = PREWARM_PATTERN.match(raw_line)
        if prewarm_match:
            prefix = prewarm_match.group(1)
            command = prewarm_match.group(2)
            locked = resolve_prewarm(command, resolver)
            resolved_lines.append(f"{prefix}{locked}")

            if current_name:
                base_command, _ = split_shell_suffix(locked)
                try:
                    tokens = shlex.split(base_command)
                except ValueError:
                    continue
                if len(tokens) >= 2 and tokens[0] == "npx":
                    pkg_index: int | None = None
                    for i in range(1, len(tokens)):
                        if tokens[i].startswith("-"):
                            continue
                        pkg_index = i
                        break
                    if pkg_index is not None:
                        mcp_to_npx_spec[current_name] = tokens[pkg_index]
            continue

        resolved_lines.append(raw_line)

    content = "\n".join(resolved_lines) + "\n"
    return content, mcp_to_npx_spec


def update_backend_npx_specs(backend_path: Path, mapping: dict[str, str]) -> None:
    """Sync backend npx package specs with bundle mapping by MCP name."""
    text = backend_path.read_text(encoding="utf-8")

    for name, pkg_spec in mapping.items():
        pattern = re.compile(
            rf'("name":\s*"{re.escape(name)}",[\s\S]*?"args":\s*\["-y",\s*")([^"]+)("\])'
        )
        text = pattern.sub(rf"\1{pkg_spec}\3", text, count=1)

    backend_path.write_text(text, encoding="utf-8")


def main() -> int:
    if not TEMPLATE_FILE.exists() or not BACKEND_FILE.exists():
        print("Required files do not exist.", file=sys.stderr)
        return 2

    resolver = Resolver()
    resolved_bundle, mapping = resolve_template_and_collect_mapping(TEMPLATE_FILE, resolver)

    with tempfile.TemporaryDirectory(prefix="castrel-mcp-refresh-") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        tmp_bundle = tmp_dir_path / "mcp-bundle.yaml"
        tmp_lock = tmp_dir_path / "mcp-bundle.lock.yaml"
        tmp_bundle.write_text(resolved_bundle, encoding="utf-8")

        lock_rc = generate_lock(tmp_bundle, tmp_lock, strict_latest=True)
        if lock_rc != 0:
            return lock_rc

    update_backend_npx_specs(BACKEND_FILE, mapping)

    print("Refreshed MCP versions successfully.")
    print(f"- Source template: {TEMPLATE_FILE}")
    print(f"- Updated: {BACKEND_FILE}")
    print("- Generated bundle/lock were temporary validation artifacts (not written to Git)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
