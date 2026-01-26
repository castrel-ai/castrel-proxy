"""Castrel Bridge Proxy - Remote command execution bridge client"""

__version__ = "0.1.5a1"
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
