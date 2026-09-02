"""
Session workspace resolver

Each chat session gets an isolated workspace directory on the host that is
bind-mounted into its sandbox container.  The layout is::

    <workspace_root>/<session_id>/
        uploads/     # attachments pulled on-demand from backend MinIO (ephemeral)
        scripts/     # execute-class scripts written before running
        artifacts/   # produced / intermediate outputs (session-local only)

Inside the container this directory is mounted at ``/workspace``.  Tools and
the agent address files with *logical* paths (``/uploads/foo``,
``/scripts/run.py``, ``/artifacts/out.txt``).  This module maps logical paths
to host and container paths and guards against path traversal so a logical
path can never escape the session workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .models import SandboxArtifact

CONTAINER_MOUNT = "/workspace"
SUBDIRS = ("uploads", "scripts", "artifacts")


class WorkspaceError(Exception):
    """Raised when a logical path is invalid or escapes the workspace."""


class SessionWorkspace:
    """Resolves and manages a single session's sandbox workspace."""

    def __init__(self, session_id: str, workspace_root: Path):
        if not session_id or "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
            raise WorkspaceError(f"Invalid session_id: {session_id!r}")
        self.session_id = session_id
        self.root = (workspace_root.expanduser() / session_id).resolve()

    def ensure(self) -> "SessionWorkspace":
        """Create the workspace directory tree if missing."""
        for sub in SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self

    def resolve_host(self, logical_path: str) -> Path:
        """
        Map a logical path (``/scripts/run.py``) to an absolute host path,
        guaranteeing the result stays inside the session workspace.
        """
        normalized = self._normalize(logical_path)
        host_path = (self.root / normalized).resolve()
        # Guard: resolved path must remain under the workspace root.
        if host_path != self.root and self.root not in host_path.parents:
            raise WorkspaceError(f"Path escapes workspace: {logical_path!r}")
        return host_path

    def container_path(self, logical_path: str) -> str:
        """Map a logical path to its path inside the container (``/workspace/...``)."""
        normalized = self._normalize(logical_path)
        # Validate against traversal via the host resolver.
        self.resolve_host(logical_path)
        if not normalized:
            return CONTAINER_MOUNT
        return f"{CONTAINER_MOUNT}/{normalized}"

    def write_script(self, logical_path: str, content: str) -> Path:
        """Write a script into the workspace, returning its host path."""
        host_path = self.resolve_host(logical_path)
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.write_text(content, encoding="utf-8")
        return host_path

    def list_artifacts(self) -> List[SandboxArtifact]:
        """List files under the artifacts directory as logical-path artifacts."""
        artifacts_dir = self.root / "artifacts"
        results: List[SandboxArtifact] = []
        if not artifacts_dir.is_dir():
            return results
        for path in sorted(artifacts_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(self.root).as_posix()
                stat = path.stat()
                results.append(
                    SandboxArtifact(
                        path=f"/{rel}",
                        size=stat.st_size,
                        modified_at=stat.st_mtime,
                    )
                )
        return results

    @staticmethod
    def _normalize(logical_path: str) -> str:
        """Normalize a logical path into a relative POSIX path without traversal."""
        raw = (logical_path or "").strip()
        raw = raw.replace("\\", "/")
        # Strip the container mount prefix and any leading slash.
        if raw.startswith(CONTAINER_MOUNT):
            raw = raw.removeprefix(CONTAINER_MOUNT)
        raw = raw.lstrip("/")
        parts: List[str] = []
        for part in raw.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                raise WorkspaceError(f"Path traversal not allowed: {logical_path!r}")
            parts.append(part)
        return "/".join(parts)
