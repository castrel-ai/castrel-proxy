"""
Castrel proxy sandbox subsystem.

Provides a second, isolated execution channel (OCI container per session)
alongside the existing host bash channel.
"""

from __future__ import annotations

from typing import Optional

from .config import SandboxConfig
from .detector import detect, select_engine
from .manager import ProxySandboxManager, SandboxError
from .models import BootstrapResult, ExecResult, SandboxArtifact, SandboxCapability

__all__ = [
    "SandboxConfig",
    "ProxySandboxManager",
    "SandboxError",
    "BootstrapResult",
    "ExecResult",
    "SandboxArtifact",
    "SandboxCapability",
    "detect",
    "select_engine",
    "get_sandbox_manager",
    "reset_sandbox_manager",
]

_manager: Optional[ProxySandboxManager] = None


def get_sandbox_manager(config: Optional[SandboxConfig] = None) -> ProxySandboxManager:
    """Return the process-wide sandbox manager, creating it on first use."""
    global _manager
    if _manager is None:
        if config is None:
            from ..core.config import get_config

            config = get_config().get_sandbox_config()
        _manager = ProxySandboxManager(config)
    return _manager


def reset_sandbox_manager() -> None:
    """Reset the global manager (primarily for tests)."""
    global _manager
    _manager = None
