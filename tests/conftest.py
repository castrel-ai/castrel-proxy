"""
Global test fixtures for castrel-bridge-proxy.

Environment isolation:
- ~/.castrel/ config directory isolated to temp dir
- WebSocket and MCP mock fixtures
- No real external connections during tests
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================
# Environment Isolation
# ============================================================

_SENSITIVE_KEYS = [
    "CASTREL_SERVER_URL",
    "CASTREL_API_KEY",
    "CASTREL_CLIENT_ID",
]

_original_env: dict[str, str | None] = {}


def _isolate_env():
    """Remove sensitive env vars before tests."""
    for key in _SENSITIVE_KEYS:
        _original_env[key] = os.environ.pop(key, None)


def _restore_env():
    """Restore original env vars after tests."""
    for key, value in _original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


_isolate_env()


@pytest.fixture(autouse=True, scope="session")
def _restore_env_after_session():
    yield
    _restore_env()


# ============================================================
# Isolated Config Directory
# ============================================================

@pytest.fixture
def isolated_config_dir(tmp_path):
    """Provide an isolated ~/.castrel/ config directory."""
    config_dir = tmp_path / ".castrel"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_config(isolated_config_dir):
    """Create a sample config.yaml in the isolated config dir."""
    import yaml

    config = {
        "server_url": "wss://test-server.example.com/ws",
        "client_id": "test-client-id-12345",
        "client_name": "test-bridge",
        "paired": True,
    }
    config_file = isolated_config_dir / "config.yaml"
    config_file.write_text(yaml.dump(config), encoding="utf-8")
    return config_file


# ============================================================
# Mock WebSocket
# ============================================================

@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection."""
    ws = AsyncMock()
    ws.send_str = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive = AsyncMock()
    ws.receive_json = AsyncMock(return_value={"type": "ping"})
    ws.close = AsyncMock()
    ws.closed = False
    return ws


@pytest.fixture
def mock_ws_session(mock_websocket):
    """Mock aiohttp WebSocket session."""
    session = AsyncMock()
    session.ws_connect = AsyncMock(return_value=mock_websocket)
    session.close = AsyncMock()
    return session


# ============================================================
# Mock MCP
# ============================================================

@pytest.fixture
def mock_mcp_server():
    """Mock MCP server connection."""
    server = AsyncMock()
    server.list_tools = AsyncMock(return_value=[
        {"name": "test_tool", "description": "A test tool", "parameters": {}},
    ])
    server.call_tool = AsyncMock(return_value={"result": "ok"})
    return server


# ============================================================
# Mock Command Executor
# ============================================================

@pytest.fixture
def mock_executor():
    """Mock command executor."""
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value={
        "exit_code": 0,
        "stdout": "command output",
        "stderr": "",
    })
    return executor


# ============================================================
# Sample Data
# ============================================================

@pytest.fixture
def sample_command_message():
    """Sample command execution message from server."""
    return {
        "type": "command",
        "id": "cmd-001",
        "command": "echo hello",
        "timeout": 30,
    }


@pytest.fixture
def sample_skill_metadata():
    """Sample SKILL.md parsed metadata."""
    return {
        "name": "test-skill",
        "description": "A test skill for unit tests",
        "version": "1.0.0",
        "scripts": ["run.sh"],
    }
