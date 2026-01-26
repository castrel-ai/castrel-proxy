"""Core functionality for Castrel Bridge Proxy"""

from .client_id import get_client_id, get_machine_metadata
from .config import Config, ConfigError, get_config
from .daemon import DaemonManager, get_daemon_manager
from .executor import CommandExecutor, ExecutionResult

__all__ = [
    "get_client_id",
    "get_machine_metadata",
    "Config",
    "ConfigError",
    "get_config",
    "DaemonManager",
    "get_daemon_manager",
    "CommandExecutor",
    "ExecutionResult",
]
