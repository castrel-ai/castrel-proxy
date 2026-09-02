"""
Container engine detector

Detects whether Docker is available on the host and whether the configured
sandbox image is present locally.  The result feeds the ``capabilities_sync``
message so the backend knows whether this proxy node can offer sandbox
execution.

Only Docker is supported.  Any Docker-compatible socket provider works:
Docker Engine (Linux), Docker Desktop, OrbStack, Colima, Rancher Desktop, etc.

Detection is best-effort and never raises: a missing engine simply yields an
``available=False`` capability with a human-readable reason.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from .config import SandboxConfig
from .models import SandboxCapability

_PROBE_TIMEOUT = 5.0


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT,
    )


def _engine_version(engine: str) -> Optional[str]:
    """Return the server version if the Docker daemon is reachable, else None."""
    try:
        proc = _run([engine, "version", "--format", "{{.Server.Version}}"])
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    version = proc.stdout.strip()
    return version or None


def _image_present(engine: str, image: str) -> bool:
    try:
        proc = _run([engine, "image", "inspect", image])
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def select_engine(config: SandboxConfig) -> Optional[str]:
    """Return ``"docker"`` if Docker is available and reachable, else None."""
    engine = "docker"
    if shutil.which(engine) and _engine_version(engine):
        return engine
    return None


def detect(config: SandboxConfig) -> SandboxCapability:
    """Detect sandbox capability for the given configuration."""
    if not config.enabled:
        return SandboxCapability(available=False, reason="sandbox disabled in config")

    engine = select_engine(config)
    if engine is None:
        return SandboxCapability(
            available=False,
            reason="Docker not found or daemon not reachable",
        )

    version = _engine_version(engine)
    image_present = _image_present(engine, config.image)
    return SandboxCapability(
        available=True,
        engine=engine,
        engine_version=version,
        image=config.image,
        image_present=image_present,
    )
