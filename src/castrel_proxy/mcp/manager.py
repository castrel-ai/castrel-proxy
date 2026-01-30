"""
MCP Manager Module

Responsible for managing MCP client connections and fetching tools information
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def convert_config_to_langchain_format(config_data: dict) -> dict:
    """
    Convert configuration to langchain-mcp-adapters format

    Args:
        config_data: Original configuration data

    Returns:
        dict: Configuration in langchain format

    Raises:
        ValueError: When configuration is invalid
    """
    langchain_config = {}

    for name, server_config in config_data.items():
        # Validate required transport key
        if "transport" not in server_config:
            error_msg = (
                f"Configuration error for server '{name}': Missing 'transport' key. "
                f"Each server must include 'transport' with one of: 'stdio', 'sse', 'http'. "
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        transport = server_config.get("transport")

        if transport == "stdio":
            # stdio type: use command and args
            if not server_config.get("command"):
                error_msg = f"Configuration error for server '{name}': Missing 'command' for stdio transport"
                logger.error(error_msg)
                raise ValueError(error_msg)

            langchain_config[name] = {
                "transport": "stdio",
                "command": server_config.get("command"),
                "args": server_config.get("args", []),
            }
            # Add environment variables if present
            if server_config.get("env"):
                langchain_config[name]["env"] = server_config.get("env")

        elif transport == "http":
            # http type: use url
            if not server_config.get("url"):
                error_msg = f"Configuration error for server '{name}': Missing 'url' for http transport"
                logger.error(error_msg)
                raise ValueError(error_msg)

            langchain_config[name] = {
                "transport": "http",
                "url": server_config.get("url"),
            }

        elif transport == "sse":
            # sse type: use url
            if not server_config.get("url"):
                error_msg = f"Configuration error for server '{name}': Missing 'url' for sse transport"
                logger.error(error_msg)
                raise ValueError(error_msg)

            langchain_config[name] = {
                "transport": "sse",
                "url": server_config.get("url"),
            }

        else:
            error_msg = (
                f"Configuration error for server '{name}': Unknown transport type '{transport}'. "
                f"Supported transports: 'stdio', 'http', 'sse'"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    return langchain_config


class MCPManager:
    """MCP manager"""

    def __init__(self, config_file: Optional[Path] = None):
        """
        Initialize MCP manager

        Args:
            config_file: Configuration file path, defaults to ~/.castrel/mcp.json
        """
        if config_file is None:
            self.config_file = Path.home() / ".castrel" / "mcp.json"
        else:
            self.config_file = Path(config_file)

        self.client: Optional[MultiServerMCPClient] = None
        self.server_configs: Dict = {}

    def load_config(self) -> Dict:
        """
        Load MCP configuration

        Returns:
            Dict: Configuration dictionary in langchain format
        """
        if not self.config_file.exists():
            logger.warning(f"MCP configuration file does not exist: {self.config_file}")
            return {}

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            mcpServers = data.get("mcpServers", {})

            logger.info(f"Loaded {len(mcpServers)} MCP configurations")
            return mcpServers

        except Exception as e:
            logger.error(f"Failed to load MCP configuration: {e}")
            return {}

    def get_server_list(self) -> List[Dict]:
        """
        Get server configuration list (for display)

        Returns:
            List[Dict]: Server configuration list
        """
        if not self.config_file.exists():
            return []

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            servers = []
            mcpServers = data.get("mcpServers", {})

            for name, config in mcpServers.items():
                servers.append(
                    {
                        "name": name,
                        "transport": config.get("transport", "stdio"),
                        "command": config.get("command", ""),
                        "args": config.get("args", []),
                        "url": config.get("url", ""),
                        "env": config.get("env", {}),
                    }
                )

            return servers

        except Exception as e:
            logger.error(f"Failed to get server list: {e}")
            return []

    async def connect_all(self) -> int:
        """
        Connect to all configured MCP services

        Returns:
            int: Number of successfully connected services

        Raises:
            SystemExit: When configuration is invalid
        """
        raw_config = self.load_config()
        if not raw_config:
            logger.info("No MCP services configured")
            return 0

        try:
            # Convert configuration to langchain format
            logger.info(f"Converting configuration for {len(raw_config)} MCP services...")
            self.server_configs = convert_config_to_langchain_format(raw_config)

            logger.info(f"Connecting to {len(self.server_configs)} MCP services...")

            # Create MultiServerMCPClient
            self.client = MultiServerMCPClient(self.server_configs)

            logger.info(f"Successfully connected to {len(self.server_configs)} MCP services")
            return len(self.server_configs)

        except ValueError as e:
            # Configuration error - exit immediately
            logger.error(f"Configuration error: {e}")
            logger.error("Exiting due to invalid MCP configuration")
            sys.exit(1)

        except Exception as e:
            logger.error(f"Failed to connect to MCP services: {e}")
            logger.error("Exiting due to MCP connection failure")
            sys.exit(1)

    async def get_all_tools(self) -> Dict[str, List[Dict]]:
        """
        Get tools from all MCP services

        Returns:
            Dict[str, List[Dict]]: All tools list (may be partial if some servers fail)
        """
        if not self.client:
            logger.error("MCP client not initialized")
            return {}

        result = {}
        total_count = 0
        failed_servers = []

        for server_name in self.server_configs:
            try:
                tools = await self.client.get_tools(server_name=server_name)
                # Convert to required format
                formatted_tools = []
                for tool in tools:
                    # Tool format returned by langchain-mcp-adapters
                    tool_info = {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.args_schema if hasattr(tool, "args_schema") else {},
                        "mcp_server": getattr(tool, "server_name", "unknown"),
                    }
                    formatted_tools.append(tool_info)
                total_count += len(formatted_tools)
                result[server_name] = formatted_tools
                logger.info(f"Retrieved {len(formatted_tools)} tool(s) from '{server_name}'")

            except Exception as e:
                failed_servers.append(server_name)
                # Log error but continue with other servers
                if "Configuration error" in str(e) or "Missing 'transport' key" in str(e):
                    logger.error(f"Configuration error for server '{server_name}': {e}")
                else:
                    logger.error(f"Failed to get tools from server '{server_name}': {e}")

        if failed_servers:
            logger.warning(
                f"Failed to retrieve tools from {len(failed_servers)} server(s): {', '.join(failed_servers)}"
            )

        if total_count == 0:
            logger.warning("No tools retrieved from any MCP server")
        else:
            logger.info(f"Retrieved {total_count} tool(s) from {len(result)} server(s)")

        return result

    async def disconnect_all(self):
        """Disconnect all MCP connections"""
        if self.client:
            try:
                # MultiServerMCPClient manages connections automatically
                self.client = None
                logger.info("All MCP services disconnected")
            except Exception as e:
                logger.error(f"Failed to disconnect MCP services: {e}")


# Global MCP manager instance
_mcp_manager = MCPManager()


def get_mcp_manager() -> MCPManager:
    """Get global MCP manager instance"""
    return _mcp_manager
