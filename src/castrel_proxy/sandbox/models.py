"""
Sandbox data models

Typed results and capability descriptors exchanged between the sandbox
manager, the backends, and the WebSocket protocol layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SandboxArtifact:
    """A single file produced inside the sandbox artifacts directory."""

    path: str  # logical path, e.g. /artifacts/report.txt
    size: int
    modified_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BootstrapResult:
    """Result of bootstrapping (creating) a per-session sandbox container."""

    session_id: str
    container_id: str
    image: str
    engine: str
    workspace: str  # host path bound into the container
    reused: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecResult:
    """Result of executing a script inside a sandbox."""

    session_id: str
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    mode: str = "untrusted"
    artifacts: List[SandboxArtifact] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["artifacts"] = [
            a.to_dict() if isinstance(a, SandboxArtifact) else a for a in self.artifacts
        ]
        return data


@dataclass
class SandboxCapability:
    """Capability descriptor reported to the backend via capabilities_sync."""

    available: bool
    engine: Optional[str] = None  # docker | podman | None
    engine_version: Optional[str] = None
    image: Optional[str] = None
    image_present: bool = False
    reason: Optional[str] = None  # why unavailable, when available is False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
