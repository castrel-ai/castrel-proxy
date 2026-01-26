"""
Configuration File Management Module

Handles reading, writing, and validating the ~/.castrel/config.yaml configuration file
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Configuration-related errors"""

    pass


class Config:
    """Configuration management class"""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize configuration manager

        Args:
            config_dir: Configuration directory path, defaults to ~/.castrel
        """
        if config_dir is None:
            self.config_dir = Path.home() / ".castrel"
        else:
            self.config_dir = Path(config_dir)

        self.config_file = self.config_dir / "config.yaml"

    def _ensure_config_dir(self):
        """Ensure configuration directory exists"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ConfigError(f"Failed to create config directory {self.config_dir}: {e}")

    def save(self, server_url: str, verification_code: str, client_id: str, workspace_id: str) -> None:
        """
        Save configuration to file

        Args:
            server_url: Server URL
            verification_code: Verification code
            client_id: Client unique identifier
            workspace_id: Workspace ID

        Raises:
            ConfigError: Raised when saving configuration fails
        """
        self._ensure_config_dir()

        config_data = {
            "server_url": server_url,
            "verification_code": verification_code,
            "client_id": client_id,
            "workspace_id": workspace_id,
            "paired_at": datetime.utcnow().isoformat() + "Z",
        }

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            raise ConfigError(f"Failed to save configuration: {e}")

    def load(self) -> dict:
        """
        Load configuration from file

        Returns:
            dict: Configuration dictionary

        Raises:
            ConfigError: Raised when configuration file doesn't exist or loading fails
        """
        if not self.config_file.exists():
            raise ConfigError("Configuration file does not exist. Please pair first using 'pair' command")

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                raise ConfigError("Configuration file is empty")

            # Validate required fields
            required_fields = ["server_url", "verification_code", "client_id", "workspace_id"]
            for field in required_fields:
                if field not in config_data:
                    raise ConfigError(f"Configuration file missing required field: {field}")

            return config_data

        except yaml.YAMLError as e:
            raise ConfigError(f"Configuration file format error: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {e}")

    def exists(self) -> bool:
        """
        Check if configuration file exists

        Returns:
            bool: True if configuration file exists, False otherwise
        """
        return self.config_file.exists()

    def delete(self) -> None:
        """
        Delete configuration file

        Raises:
            ConfigError: Raised when deletion fails
        """
        if not self.config_file.exists():
            raise ConfigError("Configuration file does not exist")

        try:
            self.config_file.unlink()
        except Exception as e:
            raise ConfigError(f"Failed to delete configuration file: {e}")

    def get_server_url(self) -> str:
        """Get server URL"""
        return self.load()["server_url"]

    def get_verification_code(self) -> str:
        """Get verification code"""
        return self.load()["verification_code"]

    def get_client_id(self) -> str:
        """Get client ID"""
        return self.load()["client_id"]

    def get_paired_at(self) -> Optional[str]:
        """Get pairing time"""
        config = self.load()
        return config.get("paired_at")

    def get_workspace_id(self) -> str:
        """Get workspace ID"""
        return self.load()["workspace_id"]


# Global configuration instance
_config = Config()


def get_config() -> Config:
    """Get global configuration instance"""
    return _config
