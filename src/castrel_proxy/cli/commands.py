"""
CLI Commands Module

Defines all command-line interface commands for Castrel Bridge Proxy
"""

import asyncio
import base64
import json
import logging
import sys
from typing import Any, Dict

import typer

from ..core.client_id import get_client_id
from ..core.config import ConfigError, get_config
from ..core.daemon import get_daemon_manager
from ..mcp.manager import get_mcp_manager
from ..network.api_client import APIError, NetworkError, PairingError, get_api_client
from ..network.websocket_client import WebSocketClient
from ..security.whitelist import init_whitelist_file

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


def decode_verification_code(verification_code: str) -> Dict[str, Any]:
    """
    Decode verification code, extracting timestamp, workspace_id, and random code

    Args:
        verification_code: Encoded verification code

    Returns:
        Dict[str, Any]: Dictionary containing ts (timestamp), wid (workspace_id), rand (random_code)

    Raises:
        ValueError: Invalid verification code format
    """
    try:
        # Add possibly missing padding characters
        padding = 4 - (len(verification_code) % 4)
        if padding != 4:
            verification_code += "=" * padding

        # Base64 decode
        decoded_bytes = base64.urlsafe_b64decode(verification_code)
        json_str = decoded_bytes.decode("utf-8")

        # Parse JSON
        code_data = json.loads(json_str)

        # Validate required fields
        if not all(key in code_data for key in ["ts", "wid", "rand"]):
            raise ValueError("Missing required fields in verification code")

        return code_data

    except Exception as e:
        raise ValueError(f"Invalid verification code format: {str(e)}")


@app.command()
def pair(
    code: str = typer.Argument(..., help="Verification code provided by server"),
    server_url: str = typer.Argument(..., help="Server URL address"),
):
    """
    Pair with server

    Pair local bridge with server using verification code. The code contains workspace ID and other
    information without needing manual input.

    Usage:
      castrel-proxy pair <verification_code> <server_url>

    Example:
      castrel-proxy pair eyJ0cyI6MTczNTA4ODQwMCwid2lkIjoiZGVmYXVsdCIsInJhbmQiOiIxMjM0NTYifQ https://server.example.com
    """
    config = get_config()
    api_client = get_api_client()

    try:
        # Decode verification code to get workspace_id
        typer.echo("Parsing verification code...")
        try:
            code_info = decode_verification_code(code)
            workspace_id = code_info["wid"]

            typer.secho("✓ Verification code parsed successfully", fg=typer.colors.GREEN)
            typer.echo(f"  Workspace ID: {workspace_id}")
        except ValueError as e:
            typer.secho(f"✗ Invalid verification code format: {e}", fg=typer.colors.RED, err=True)
            typer.echo("Hint: Please ensure you use the complete verification code from the server", err=True)
            raise typer.Exit(1)

        # Generate client ID
        typer.echo("\nGenerating client identifier...")
        client_id = get_client_id()
        typer.echo(f"Client ID: {client_id}")

        # Connect to server and verify
        typer.echo(f"\nConnecting to server: {server_url}")
        typer.echo(f"Using verification code: {code}")
        typer.echo(f"Workspace ID: {workspace_id}")

        # Call server verification endpoint
        api_client.verify_pairing(server_url, code, client_id, workspace_id)

        # Verification successful, save configuration
        config.save(server_url, code, client_id, workspace_id)

        # Initialize whitelist configuration file
        whitelist_path = init_whitelist_file()
        typer.echo(f"Whitelist configuration initialized: {whitelist_path}")

        typer.secho("✓ Pairing successful!", fg=typer.colors.GREEN)
        typer.echo(f"Configuration saved to: {config.config_file}")

        # Try to load and send MCP tools information
        typer.echo("\nLoading MCP services...")
        try:
            mcp_manager = get_mcp_manager()

            # Asynchronously connect to MCP and get tools
            async def sync_mcp_tools():
                # Connect all MCP services
                count = await mcp_manager.connect_all()
                if count == 0:
                    typer.echo("No MCP services configured, not registering MCP info")
                    await api_client._send_client_info(server_url, client_id, code, workspace_id, {})
                    return

                typer.echo(f"Connected to {count} MCP service(s)")

                # Get all tools
                tools = await mcp_manager.get_all_tools()
                typer.echo(f"Retrieved {len(tools)} tool(s)")

                # Send to server
                if tools:
                    typer.echo("Sending MCP tools information to server...")
                    await api_client._send_client_info(server_url, client_id, code, workspace_id, tools)
                    typer.secho("✓ MCP tools information synchronized", fg=typer.colors.GREEN)

                # Disconnect MCP connections
                await mcp_manager.disconnect_all()

            asyncio.run(sync_mcp_tools())

        except Exception as e:
            typer.secho(f"⚠ MCP synchronization failed: {e}", fg=typer.colors.YELLOW)
            typer.echo("Hint: You can manually synchronize MCP information later")

        typer.echo("\nHint: Use 'castrel-proxy start' to start bridge service")

    except PairingError as e:
        typer.secho(f"✗ Pairing failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except NetworkError as e:
        typer.secho(f"✗ Network error: {e}", fg=typer.colors.RED, err=True)
        typer.echo("Please check if server address is correct and network connection is normal", err=True)
        raise typer.Exit(1)
    except ConfigError as e:
        typer.secho(f"✗ Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except APIError as e:
        typer.secho(f"✗ API error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ Unknown error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def start(
    daemon: bool = typer.Option(
        True, "--daemon/--foreground", "-d/-f", help="Run in background (default) or foreground"
    ),
):
    """
    Start bridge service

    Start bridge and connect to paired server.

    Run in background (default):
      castrel-proxy start
      castrel-proxy start --daemon
      castrel-proxy start -d

    Run in foreground:
      castrel-proxy start --foreground
      castrel-proxy start -f
    """
    config = get_config()

    try:
        # Load configuration
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]

        typer.secho("=== Starting Bridge Service ===", bold=True)
        typer.echo(f"Server: {server_url}")
        typer.echo(f"Client ID: {client_id}")
        typer.echo(f"Workspace ID: {workspace_id}")

        if daemon:
            # Check if Windows
            if sys.platform == "win32":
                typer.secho("✗ Background mode is not supported on Windows", fg=typer.colors.YELLOW)
                typer.echo("Hint: Use '--foreground' or '-f' flag to run in foreground mode")
                raise typer.Exit(1)

            # Get daemon manager
            daemon_mgr = get_daemon_manager()

            # Check if already running
            if daemon_mgr.is_running():
                pid = daemon_mgr.get_pid()
                typer.secho(f"✗ Bridge is already running with PID {pid}", fg=typer.colors.YELLOW)
                typer.echo("Hint: Use 'castrel-proxy stop' to stop it first")
                raise typer.Exit(1)

            typer.echo("\nStarting bridge in background...")
            typer.echo(f"PID file: {daemon_mgr.pid_file}")
            typer.echo(f"Log file: {daemon_mgr.log_file}")

            # Daemonize the process
            try:
                daemon_mgr.daemonize()

                # Configure logging to file
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    handlers=[logging.FileHandler(daemon_mgr.log_file), logging.StreamHandler()],
                )

                logger = logging.getLogger(__name__)
                logger.info("=== Bridge Service Started in Background ===")
                logger.info(f"Server: {server_url}")
                logger.info(f"Client ID: {client_id}")
                logger.info(f"Workspace ID: {workspace_id}")

                # Create and run WebSocket client
                ws_client = WebSocketClient(
                    server_url=server_url,
                    client_id=client_id,
                    verification_code=verification_code,
                    workspace_id=workspace_id,
                )

                asyncio.run(ws_client.run())

            except RuntimeError as e:
                # Already running error
                typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1)
            except Exception as e:
                if daemon_mgr.get_pid() is not None:
                    # Log error in daemon mode
                    logging.error(f"Runtime error: {e}", exc_info=True)
                raise typer.Exit(1)

            # This line is only reached by parent process before exit
            typer.secho("✓ Bridge started in background", fg=typer.colors.GREEN)
            typer.echo(f"PID: {daemon_mgr.get_pid()}")
            typer.echo("Hint: Use 'castrel-proxy logs -f' to follow logs")
            typer.echo("Hint: Use 'castrel-proxy stop' to stop service")

        else:
            typer.echo("\nRunning in foreground mode...")
            typer.echo("Connecting to server...")
            typer.echo("Hint: Press Ctrl+C to stop service\n")

            # Create WebSocket client
            ws_client = WebSocketClient(
                server_url=server_url,
                client_id=client_id,
                verification_code=verification_code,
                workspace_id=workspace_id,
            )

            # Run client
            try:
                asyncio.run(ws_client.run())
            except KeyboardInterrupt:
                typer.echo("\nStopping bridge...")
                typer.secho("✓ Bridge stopped", fg=typer.colors.GREEN)
            except Exception as e:
                typer.secho(f"\n✗ Runtime error: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1)

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("Hint: Please pair first using 'castrel-proxy pair' command", err=True)
        raise typer.Exit(1)


@app.command()
def config():
    """
    View configuration information
    """
    config_obj = get_config()

    try:
        # Load configuration
        config_data = config_obj.load()

        typer.secho("=== Configuration Information ===", bold=True)
        typer.echo(f"Config file: {config_obj.config_file}")
        typer.echo(f"Server URL: {config_data['server_url']}")
        typer.echo(f"Verification code: {config_data['verification_code']}")
        typer.echo(f"Client ID: {config_data['client_id']}")
        typer.echo(f"Workspace ID: {config_data['workspace_id']}")

        if "paired_at" in config_data:
            typer.echo(f"Paired at: {config_data['paired_at']}")

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def status():
    """
    View bridge running status
    """
    config = get_config()

    try:
        # Load configuration
        config_data = config.load()

        typer.secho("=== Bridge Status ===", bold=True)
        typer.echo("Pairing status: ", nl=False)
        typer.secho("Paired", fg=typer.colors.GREEN)
        typer.echo(f"Server: {config_data['server_url']}")
        typer.echo(f"Client ID: {config_data['client_id']}")
        typer.echo(f"Workspace ID: {config_data['workspace_id']}")

        if "paired_at" in config_data:
            typer.echo(f"Paired at: {config_data['paired_at']}")

        # Check running status
        daemon_mgr = get_daemon_manager()
        typer.echo("Running status: ", nl=False)

        if daemon_mgr.is_running():
            pid = daemon_mgr.get_pid()
            typer.secho(f"Running (PID: {pid})", fg=typer.colors.GREEN)
            typer.echo(f"PID file: {daemon_mgr.pid_file}")
            typer.echo(f"Log file: {daemon_mgr.log_file}")
            typer.echo("Hint: Use 'castrel-proxy logs -f' to follow logs")
        else:
            typer.secho("Not running", fg=typer.colors.YELLOW)
            typer.echo("Hint: Use 'castrel-proxy start' to start service")

    except ConfigError:
        typer.secho("=== Bridge Status ===", bold=True)
        typer.echo("Pairing status: ", nl=False)
        typer.secho("Not paired", fg=typer.colors.YELLOW)
        typer.echo("Hint: Use 'castrel-proxy pair' command to pair")


@app.command()
def stop():
    """
    Stop bridge service

    Stop the background daemon process if running.
    """
    daemon_mgr = get_daemon_manager()

    # Check if running
    if not daemon_mgr.is_running():
        typer.secho("✗ Bridge is not running", fg=typer.colors.YELLOW)
        # Clean up stale PID file if exists
        if daemon_mgr.pid_file.exists():
            daemon_mgr.pid_file.unlink()
            typer.echo("Cleaned up stale PID file")
        raise typer.Exit(0)

    pid = daemon_mgr.get_pid()
    typer.echo(f"Stopping bridge (PID: {pid})...")

    # Stop the daemon
    if daemon_mgr.stop():
        typer.secho("✓ Bridge stopped", fg=typer.colors.GREEN)
    else:
        typer.secho("✗ Failed to stop bridge", fg=typer.colors.RED, err=True)
        typer.echo(f"Hint: Try manually killing process {pid}")
        raise typer.Exit(1)


@app.command()
def unpair():
    """
    Unpair from server
    """
    config = get_config()

    try:
        # Check if configuration exists
        if not config.exists():
            typer.secho("✗ Pairing configuration not found", fg=typer.colors.YELLOW)
            raise typer.Exit(0)

        # Display current configuration information
        config_data = config.load()
        typer.echo(f"Currently paired server: {config_data['server_url']}")
        typer.echo(f"Client ID: {config_data['client_id']}")
        typer.echo(f"Workspace ID: {config_data['workspace_id']}")

        # Confirm deletion
        confirm = typer.confirm("Are you sure you want to unpair?")
        if confirm:
            typer.echo("Unpairing...")
            config.delete()
            typer.secho("✓ Unpaired", fg=typer.colors.GREEN)
        else:
            typer.echo("Cancelled")

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Display last N lines of logs"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow logs in real-time"),
):
    """
    View bridge logs

    Display logs from the background daemon process.
    """
    daemon_mgr = get_daemon_manager()

    # Check if log file exists
    if not daemon_mgr.log_file.exists():
        typer.secho("✗ Log file not found", fg=typer.colors.YELLOW)
        typer.echo(f"Expected location: {daemon_mgr.log_file}")
        typer.echo("Hint: Start the bridge first using 'castrel-proxy start'")
        raise typer.Exit(1)

    if follow:
        # Follow logs in real-time
        typer.echo(f"Following logs from {daemon_mgr.log_file}... (Ctrl+C to exit)\n")
        try:
            import subprocess

            # Use tail -f to follow logs
            subprocess.run(["tail", "-f", str(daemon_mgr.log_file)])
        except KeyboardInterrupt:
            typer.echo("\nStopped following logs")
        except FileNotFoundError:
            # tail command not available, fallback to Python implementation
            typer.secho("✗ 'tail' command not found", fg=typer.colors.YELLOW)
            typer.echo("Hint: Install coreutils or use '--lines' without '--follow'")
            raise typer.Exit(1)
    else:
        # Display last N lines
        typer.echo(f"Last {lines} lines from {daemon_mgr.log_file}:\n")
        try:
            with open(daemon_mgr.log_file, "r") as f:
                all_lines = f.readlines()
                last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                for line in last_lines:
                    typer.echo(line.rstrip())
        except Exception as e:
            typer.secho(f"✗ Failed to read log file: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)


@app.command()
def mcp_list():
    """
    List configured MCP services
    """
    mcp_manager = get_mcp_manager()
    servers = mcp_manager.get_server_list()

    if not servers:
        typer.echo("No MCP services configured")
        typer.echo(f"Config file: {mcp_manager.config_file}")
        typer.echo("Hint: Refer to mcp.json.example to create configuration file")
        return

    typer.secho("=== MCP Service List ===", bold=True)
    typer.echo(f"Config file: {mcp_manager.config_file}")
    typer.echo(f"Total {len(servers)} service(s):\n")

    for server in servers:
        name = server["name"]
        transport = server["transport"]

        typer.echo(f"📦 {name}")
        typer.echo(f"   Transport: {transport}")

        if transport == "stdio":
            command = server["command"]
            args = server["args"]
            typer.echo(f"   Command: {command} {' '.join(args)}")
            if server["env"]:
                typer.echo(f"   Environment variables: {len(server['env'])} var(s)")
        elif transport == "http":
            typer.echo(f"   URL: {server['url']}")

        typer.echo()


@app.command()
def mcp_sync():
    """
    Synchronize MCP tools information to server
    """
    config = get_config()

    try:
        # Load configuration
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]

        typer.secho("=== Synchronizing MCP Tools ===", bold=True)
        typer.echo(f"Server: {server_url}")
        typer.echo(f"Client ID: {client_id}")
        typer.echo(f"Workspace ID: {workspace_id}\n")

        mcp_manager = get_mcp_manager()
        api_client = get_api_client()

        # Asynchronously synchronize MCP tools
        async def sync_mcp_tools():
            # Connect all MCP services
            typer.echo("Connecting to MCP services...")
            count = await mcp_manager.connect_all()

            if count == 0:
                typer.secho("✗ No available MCP services", fg=typer.colors.YELLOW)
                typer.echo(f"Config file: {mcp_manager.config_file}")
                typer.echo("Hint: Use 'castrel-proxy mcp-list' to view configuration")
                return

            typer.secho(f"✓ Connected to {count} MCP service(s)", fg=typer.colors.GREEN)

            # Get all tools
            typer.echo("\nRetrieving tools information...")
            tools = await mcp_manager.get_all_tools()

            # Calculate total tool count
            total_tools = sum(len(tool_list) for tool_list in tools.values())
            typer.secho(f"✓ Retrieved {total_tools} tool(s)", fg=typer.colors.GREEN)

            # Display tools overview
            if tools:
                typer.echo("\nTools overview:")
                for server, tool_list in tools.items():
                    typer.echo(f"  {server}: {len(tool_list)} tool(s)")
                    for tool in tool_list[:3]:  # Only display first 3
                        typer.echo(f"    - {tool['name']}")
                    if len(tool_list) > 3:
                        typer.echo(f"    ... and {len(tool_list) - 3} more")

            # Send to server
            if tools:
                typer.echo("\nSending to server...")
                await api_client._send_client_info(server_url, client_id, verification_code, workspace_id, tools)
                typer.secho("✓ MCP tools information synchronized", fg=typer.colors.GREEN)
            else:
                typer.secho("⚠ No tools to synchronize", fg=typer.colors.YELLOW)

            # Disconnect MCP connections
            await mcp_manager.disconnect_all()

        asyncio.run(sync_mcp_tools())

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("Hint: Please pair first using 'castrel-proxy pair' command", err=True)
        raise typer.Exit(1)
    except (NetworkError, APIError) as e:
        typer.secho(f"✗ Synchronization failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ Unknown error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def run():
    """Entry point for the CLI application"""
    app()


if __name__ == "__main__":
    run()
