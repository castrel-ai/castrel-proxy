"""Directory operations for bridge-native filesystem browsing."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _expand_path(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(path))).resolve()


def _coerce_limit(limit: int) -> int:
    try:
        return max(1, int(limit or 20))
    except (TypeError, ValueError):
        return 20


def _list_root_directories(limit: int) -> list[str]:
    """Return available root directories for the current platform."""
    normalized_limit = _coerce_limit(limit)
    roots: list[str] = []
    if os.name == "nt":
        for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_path = Path(f"{drive}:/")
            if drive_path.exists():
                roots.append(str(drive_path))
                if len(roots) >= normalized_limit:
                    break
        return roots[:normalized_limit]

    root_path = Path("/")
    try:
        children = sorted(root_path.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        logger.warning("[DIR-OPS] Failed to list root directories: %s", exc)
        return []

    for child in children:
        if child.is_dir():
            roots.append(str(child))
            if len(roots) >= normalized_limit:
                break
    return roots[:normalized_limit]


def _list_directory_candidates(path: str | None, limit: int) -> list[str]:
    """List a directory and its immediate child directories."""
    normalized_limit = _coerce_limit(limit)
    if not path:
        return _list_root_directories(normalized_limit)

    try:
        target = _expand_path(path)
    except Exception as exc:
        logger.warning("[DIR-OPS] Failed to normalize directory %s: %s", path, exc)
        return []

    directories: list[str] = []
    if target.is_dir():
        directories.append(str(target))
        try:
            children = sorted(target.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            logger.warning("[DIR-OPS] Failed to list directory %s: %s", target, exc)
            return directories[:normalized_limit]

        for child in children:
            if child.is_dir():
                try:
                    directories.append(str(child.resolve()))
                except OSError:
                    continue
                if len(directories) >= normalized_limit:
                    break
    return directories[:normalized_limit]


def _search_directory_candidates(keyword: str, limit: int) -> list[str]:
    """Search directories by absolute-path prefix."""
    normalized = (keyword or "").strip()
    if not normalized:
        return []

    search_path = Path(os.path.expanduser(os.path.expandvars(normalized)))
    if not search_path.is_absolute():
        return []

    normalized_prefix = str(search_path)
    results: list[str] = []
    seen: set[str] = set()

    candidate_directories = [search_path]
    parent = search_path.parent
    if parent != search_path and parent.exists():
        try:
            candidate_directories.extend(
                sorted(parent.iterdir(), key=lambda item: item.name.lower())
            )
        except OSError:
            pass

    for candidate in candidate_directories:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.exists() or not resolved.is_dir():
            continue

        resolved_str = str(resolved)
        if not resolved_str.startswith(normalized_prefix):
            continue
        if resolved_str in seen:
            continue
        seen.add(resolved_str)
        results.append(resolved_str)
        if len(results) >= _coerce_limit(limit):
            break

    return results


def list_allowed_directories(limit: int = 20) -> dict[str, Any]:
    return {
        "success": True,
        "directories": _list_root_directories(limit),
    }


def list_directory(path: str | None, limit: int = 20) -> dict[str, Any]:
    return {
        "success": True,
        "directories": _list_directory_candidates(path, limit),
    }


def search_directories(keyword: str, limit: int = 20) -> dict[str, Any]:
    return {
        "success": True,
        "directories": _search_directory_candidates(keyword, limit),
    }
