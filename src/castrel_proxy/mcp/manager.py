"""
MCP Manager Module

Responsible for managing MCP client connections and fetching tools information
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def _detect_transport(name: str, server_config: dict) -> str:
    """
    Auto-detect transport type from server configuration fields.

    Priority: transport > type > auto-detect by command/url fields.
    Compatible with Claude Desktop, Cursor, VS Code, Claude Code SDK, OpenAI Codex.

    Args:
        name: Server name (for error messages)
        server_config: Server configuration dict

    Returns:
        Detected transport type: 'stdio', 'http', or 'sse'

    Raises:
        ValueError: When transport cannot be determined
    """
    transport = server_config.get("transport") or server_config.get("type")

    if transport:
        if transport in ("stdio", "http", "sse"):
            return transport
        # Normalize streamableHttp variants to "http"
        # (langchain-mcp-adapters treats "http" as streamable HTTP)
        if transport.lower().replace("-", "_").replace(" ", "") in (
            "streamablehttp", "streamable_http",
        ):
            return "http"
        raise ValueError(
            f"Configuration error for server '{name}': Unknown transport type '{transport}'. "
            f"Supported: 'stdio', 'http', 'sse', 'streamableHttp'"
        )

    if server_config.get("command"):
        return "stdio"
    if server_config.get("url"):
        return "http"

    raise ValueError(
        f"Configuration error for server '{name}': Cannot determine transport type. "
        f"Provide 'command' (for local stdio) or 'url' (for remote http/sse)."
    )


def convert_config_to_langchain_format(config_data: dict) -> dict:
    """
    Convert configuration to langchain-mcp-adapters format.

    Supports all major MCP config formats (Claude Desktop, Cursor, VS Code, etc.)
    by auto-detecting transport from command/url fields.

    Args:
        config_data: Original configuration data (mcpServers dict)

    Returns:
        dict: Configuration in langchain format

    Raises:
        ValueError: When configuration is invalid
    """
    langchain_config = {}

    for name, server_config in config_data.items():
        transport = _detect_transport(name, server_config)

        if transport == "stdio":
            if not server_config.get("command"):
                raise ValueError(f"Configuration error for server '{name}': Missing 'command' for stdio transport")

            entry = {
                "transport": "stdio",
                "command": server_config["command"],
                "args": server_config.get("args", []),
            }
            if server_config.get("env"):
                entry["env"] = server_config["env"]
            langchain_config[name] = entry

        else:
            if not server_config.get("url"):
                raise ValueError(f"Configuration error for server '{name}': Missing 'url' for {transport} transport")

            langchain_config[name] = {
                "transport": transport,
                "url": server_config["url"],
            }
            if server_config.get("headers"):
                langchain_config[name]["headers"] = server_config["headers"]

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
            Dict: Configuration dictionary (raw mcpServers content)
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

    def get_raw_configs(self) -> Dict[str, Dict]:
        """
        Get raw MCP server configurations for reporting.

        Reads mcp.json and returns each server's config as-is,
        without connecting to MCP servers or fetching tools.

        Returns:
            Dict mapping server name to its raw config dict.
        """
        return self.load_config()

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
                try:
                    transport = _detect_transport(name, config)
                except ValueError:
                    transport = "unknown"
                servers.append(
                    {
                        "name": name,
                        "transport": transport,
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

    async def connect_all(self, strict: bool = True) -> int:
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
            logger.error(f"Configuration error: {e}")
            if strict:
                logger.error("Exiting due to invalid MCP configuration")
                sys.exit(1)
            self.client = None
            self.server_configs = {}
            return 0

        except Exception as e:
            logger.error(f"Failed to connect to MCP services: {e}")
            if strict:
                logger.error("Exiting due to MCP connection failure")
                sys.exit(1)
            self.client = None
            self.server_configs = {}
            return 0

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
                        "mcp_server": server_name,
                    }
                    formatted_tools.append(tool_info)
                total_count += len(formatted_tools)
                result[server_name] = formatted_tools
                logger.info(f"Retrieved {len(formatted_tools)} tool(s) from '{server_name}'")

            except Exception as e:
                failed_servers.append(server_name)
                # For configuration errors, always error
                if "Configuration error" in str(e) or "Missing 'transport' key" in str(e):
                    logger.error(f"Configuration error for server '{server_name}': {e}")
                else:
                    # HTTP/SSE servers may be temporarily unavailable (e.g. started on-demand)
                    transport = self.server_configs.get(server_name, {}).get("transport", "stdio")
                    if transport in ("http", "sse"):
                        logger.warning(f"MCP server '{server_name}' not available (will retry when called): {e}")
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

    async def get_tools_schema(self) -> Dict[str, List[Dict]]:
        """
        Get JSON-serializable tool schemas from all connected MCP servers.

        Returns actual tool definitions (name, description, inputSchema)
        so the AI knows what parameters each tool requires.

        Returns:
            Dict mapping server name to list of tool schema dicts.
        """
        if not self.client:
            logger.warning("MCP client not initialized, cannot fetch tool schemas")
            return {}

        result = {}
        total_count = 0

        for server_name in self.server_configs:
            try:
                tools = await self.client.get_tools(server_name=server_name)
                tool_schemas = []
                for tool in tools:
                    schema: Dict = {
                        "name": tool.name,
                        "description": tool.description or "",
                    }
                    args_schema = getattr(tool, "args_schema", None)
                    if args_schema is not None:
                        if isinstance(args_schema, dict):
                            schema["inputSchema"] = args_schema
                        elif hasattr(args_schema, "model_json_schema"):
                            schema["inputSchema"] = args_schema.model_json_schema()
                        elif hasattr(args_schema, "schema"):
                            schema["inputSchema"] = args_schema.schema()
                        else:
                            schema["inputSchema"] = {}
                    else:
                        schema["inputSchema"] = {}
                    tool_schemas.append(schema)

                total_count += len(tool_schemas)
                result[server_name] = tool_schemas
                logger.info(f"Retrieved schema for {len(tool_schemas)} tool(s) from '{server_name}'")

            except Exception as e:
                logger.warning(f"Failed to get tool schemas from '{server_name}': {e}")

        logger.info(f"Total tool schemas retrieved: {total_count} from {len(result)} server(s)")
        return result

    async def get_tools_schema_resilient(
        self,
        raw_config: Optional[Dict[str, Dict]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Fetch tool schemas one server at a time.

        This isolates slow or unavailable MCP servers so a timeout on one server
        does not prevent schemas from being retrieved from the others.

        Args:
            raw_config: Optional raw mcpServers config. Defaults to loading from disk.
            timeout: Optional timeout in seconds applied per server.

        Returns:
            Dict mapping server name to list of tool schema dicts.
        """
        raw_config = raw_config or self.load_config()
        if not raw_config:
            logger.info("No MCP services configured")
            return {}

        result: Dict[str, List[Dict]] = {}
        total_count = 0

        for server_name, server_config in raw_config.items():
            try:
                isolated_config = convert_config_to_langchain_format({server_name: server_config})
                isolated_client = MultiServerMCPClient(isolated_config)

                get_tools_coro = isolated_client.get_tools(server_name=server_name)
                tools = await asyncio.wait_for(get_tools_coro, timeout=timeout) if timeout else await get_tools_coro

                tool_schemas = []
                for tool in tools:
                    schema: Dict = {
                        "name": tool.name,
                        "description": tool.description or "",
                    }
                    args_schema = getattr(tool, "args_schema", None)
                    if args_schema is not None:
                        if isinstance(args_schema, dict):
                            schema["inputSchema"] = args_schema
                        elif hasattr(args_schema, "model_json_schema"):
                            schema["inputSchema"] = args_schema.model_json_schema()
                        elif hasattr(args_schema, "schema"):
                            schema["inputSchema"] = args_schema.schema()
                        else:
                            schema["inputSchema"] = {}
                    else:
                        schema["inputSchema"] = {}
                    tool_schemas.append(schema)

                total_count += len(tool_schemas)
                result[server_name] = tool_schemas
                logger.info(
                    f"Retrieved schema for {len(tool_schemas)} tool(s) from '{server_name}' using isolated sync"
                )
            except TimeoutError:
                logger.warning(f"Timed out while fetching tool schemas from '{server_name}'")
            except ValueError as e:
                logger.warning(f"Skipping MCP server '{server_name}' due to configuration error: {e}")
            except Exception as e:
                logger.warning(f"Failed to get tool schemas from '{server_name}' during isolated sync: {e}")

        logger.info(f"Isolated tool schema sync retrieved {total_count} tool(s) from {len(result)} server(s)")
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

    def _read_raw_config(self) -> dict:
        """Read raw mcp.json content"""
        if not self.config_file.exists():
            return {"mcpServers": {}}
        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_raw_config(self, data: dict) -> None:
        """Write mcp.json"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def install_server(self, name: str, config: dict, env_defaults: Optional[Dict] = None) -> bool:
        """
        Install (add or update) an MCP server config into mcp.json.

        If the existing entry already has env configured, preserve it and only
        update non-env fields. If no existing env, write the full config.
        Also writes mcp.json.example with env values replaced by placeholder text.

        Args:
            name: MCP server name (unique identifier)
            config: Config dict containing transport/command/args/url/env fields
            env_defaults: Optional env variable template {KEY: {placeholder, description, required}}
        Returns:
            True on success
        """
        try:
            data = self._read_raw_config()
            existing = data.get("mcpServers", {}).get(name, {})

            # Preserve existing env if already configured; only overwrite non-env parts
            if existing.get("env"):
                merged = {k: v for k, v in config.items() if k != "env"}
                merged["env"] = existing["env"]
                logger.info(f"[MCP-INSTALL] Preserving existing env for: {name}")
            else:
                merged = config

            data.setdefault("mcpServers", {})[name] = merged
            self._write_raw_config(data)
            # Reset client so next tool_call reconnects
            self.client = None
            logger.info(f"[MCP-INSTALL] Installed MCP server: {name}")

            # Always write example file (overwrite the corresponding entry)
            self._write_example_config(name, config, env_defaults or {})
            return True
        except Exception as e:
            logger.error(f"[MCP-INSTALL] Failed to install {name}: {e}")
            return False

    def _write_example_config(self, name: str, config: dict, env_defaults: Dict) -> None:
        """
        Write mcp.json.example with env values replaced by placeholder text.
        Always overwrites the entry for the given server name.

        Env keys are sourced from both config["env"] and env_defaults keys,
        so that env vars show up in the example even when no real values were sent.

        Args:
            name: MCP server name
            config: Config dict (may contain real env values)
            env_defaults: env variable metadata {KEY: {placeholder, description, required}}
        """
        example_file = self.config_file.parent / "mcp.json.example"
        try:
            # Read existing example file or start fresh
            if example_file.exists():
                with open(example_file, "r", encoding="utf-8") as f:
                    example_data = json.load(f)
            else:
                example_data = {"mcpServers": {}}

            # Build example config: same as real config but env values are placeholders
            example_config = {k: v for k, v in config.items() if k != "env"}

            # Collect env keys from both actual env and env_defaults
            all_env_keys = set(config.get("env", {}).keys()) | set(env_defaults.keys())
            if all_env_keys:
                example_env = {}
                for key in all_env_keys:
                    meta = env_defaults.get(key, {})
                    placeholder = meta.get("placeholder") if isinstance(meta, dict) else None
                    example_env[key] = placeholder if placeholder else f"<{key}>"
                example_config["env"] = example_env

            # Always overwrite the example entry for this server
            example_data.setdefault("mcpServers", {})[name] = example_config
            example_file.parent.mkdir(parents=True, exist_ok=True)
            with open(example_file, "w", encoding="utf-8") as f:
                json.dump(example_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[MCP-INSTALL] Written example config: {example_file}")
        except Exception as e:
            logger.error(f"[MCP-INSTALL] Failed to write example config for {name}: {e}")

    def remove_server(self, name: str) -> bool:
        """
        Remove an MCP server config from mcp.json.

        Args:
            name: MCP server name
        Returns:
            True on success (also True if name doesn't exist)
        """
        try:
            data = self._read_raw_config()
            servers = data.get("mcpServers", {})
            if name in servers:
                del servers[name]
                data["mcpServers"] = servers
                self._write_raw_config(data)
                self.client = None
                logger.info(f"[MCP-REMOVE] Removed MCP server: {name}")
            else:
                logger.warning(f"[MCP-REMOVE] Server not found: {name}")

            # Also remove from example file
            example_file = self.config_file.parent / "mcp.json.example"
            if example_file.exists():
                try:
                    with open(example_file, "r", encoding="utf-8") as f:
                        example_data = json.load(f)
                    if name in example_data.get("mcpServers", {}):
                        del example_data["mcpServers"][name]
                        with open(example_file, "w", encoding="utf-8") as f:
                            json.dump(example_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.warning(f"[MCP-REMOVE] Failed to update example config for {name}: {e}")

            return True
        except Exception as e:
            logger.error(f"[MCP-REMOVE] Failed to remove {name}: {e}")
            return False


# Global MCP manager instance
_mcp_manager = MCPManager()


def get_mcp_manager() -> MCPManager:
    """Get global MCP manager instance"""
    return _mcp_manager
