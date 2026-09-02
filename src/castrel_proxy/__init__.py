"""Castrel Bridge Proxy - Remote command execution bridge client"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("castrel-proxy")
except PackageNotFoundError:
    __version__ = "0.1.11"

__author__ = "Castrel Team"
__license__ = "MIT"

from .core.client_id import get_client_id, get_machine_metadata
from .core.config import Config, ConfigError, get_config
from .network.api_client import APIClient, APIError, NetworkError, PairingError

__all__ = [
    "__version__",
    "get_client_id",
    "get_machine_metadata",
    "Config",
    "ConfigError",
    "get_config",
    "APIClient",
    "APIError",
    "NetworkError",
    "PairingError",
]
