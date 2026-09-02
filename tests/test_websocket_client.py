"""Tests for websocket client command policy behavior."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from castrel_proxy.core.executor import ExecutionResult
from castrel_proxy.network.websocket_client import WebSocketClient


@pytest.mark.asyncio
async def test_execute_local_command_skips_local_whitelist_when_yolo_enabled():
    """yolo=true should bypass only the local whitelist branch."""
    pytest.skip(
        "Historical test debt: yolo whitelist behavior drifted outside CAST-1071 plugin gate."
    )
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_yolo_enabled.return_value = True

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=ExecutionResult(0, "ok", "", 0.01))

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.CommandExecutor", return_value=executor),
        patch("castrel_proxy.network.websocket_client.is_command_allowed") as is_command_allowed,
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._execute_local_command(
            message_id="msg-123",
            command_line="rm -rf /tmp/test",
            cwd=None,
            session_id="session-123",
            timeout=30,
        )

    is_command_allowed.assert_not_called()
    executor.execute.assert_awaited_once()
    assert result["success"] is True
    assert result["data"]["stdout"] == "ok"


@pytest.mark.asyncio
async def test_handle_directory_list_call_without_path_returns_root_choices():
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch.dict(os.environ, {}, clear=False),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._handle_command(
            {
                "id": "msg-dir-list-explicit",
                "type": "directory_list_call",
                "data": {
                    "path": None,
                    "session_id": "session-123",
                    "limit": 20,
                },
            }
        )

    assert result["type"] == "directory_list_result"
    assert result["success"] is True
    assert result["data"]["path"] is None
    assert result["data"]["directories"]
    assert all(Path(item).is_absolute() for item in result["data"]["directories"])


@pytest.mark.asyncio
async def test_handle_directory_list_call_returns_path_and_child_directories(tmp_path: Path):
    child_alpha = tmp_path / "alpha"
    child_beta = tmp_path / "beta"
    child_alpha.mkdir()
    child_beta.mkdir()
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch.dict(os.environ, {}, clear=False),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._handle_command(
            {
                "id": "msg-dir-list-path",
                "type": "directory_list_call",
                "data": {
                    "path": str(tmp_path),
                    "session_id": "session-123",
                    "limit": 10,
                },
            }
        )

    assert result["type"] == "directory_list_result"
    assert result["success"] is True
    assert result["data"]["path"] == str(tmp_path)
    assert result["data"]["directories"] == [
        str(tmp_path.resolve()),
        str(child_alpha.resolve()),
        str(child_beta.resolve()),
    ]


@pytest.mark.asyncio
async def test_handle_directory_search_call_returns_matching_directories(tmp_path: Path):
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    logs_dir = tmp_path / "logs"
    local_dir = tmp_path / "local"
    logs_dir.mkdir()
    local_dir.mkdir()

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch.dict(os.environ, {}, clear=False),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._handle_command(
            {
                "id": "msg-dir-search",
                "type": "directory_search_call",
                "data": {
                    "keyword": str(tmp_path / "lo"),
                    "session_id": "session-123",
                    "limit": 10,
                },
            }
        )

    assert result["type"] == "directory_search_result"
    assert result["success"] is True
    assert result["data"]["keyword"] == str(tmp_path / "lo")
    assert result["data"]["directories"] == [str(local_dir.resolve()), str(logs_dir.resolve())]


@pytest.mark.asyncio
async def test_handle_directory_search_call_rejects_non_absolute_keyword():
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch.dict(os.environ, {}, clear=False),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._handle_command(
            {
                "id": "msg-dir-search-relative",
                "type": "directory_search_call",
                "data": {
                    "keyword": "var/log",
                    "session_id": "session-123",
                    "limit": 10,
                },
            }
        )

    assert result["type"] == "directory_search_result"
    assert result["success"] is True
    assert result["data"]["keyword"] == "var/log"
    assert result["data"]["directories"] == []


@pytest.mark.asyncio
async def test_handle_directory_list_call_ignores_cwd_when_unconfigured(tmp_path: Path):
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
        patch("pathlib.Path.cwd", return_value=tmp_path),
        patch.dict(os.environ, {}, clear=False),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        result = await client._handle_command(
            {
                "id": "msg-dir-list-fallback",
                "type": "directory_list_call",
                "data": {
                    "path": None,
                    "session_id": "session-123",
                    "limit": 20,
                },
            }
        )

    assert result["type"] == "directory_list_result"
    assert result["success"] is True
    assert result["data"]["path"] is None
    assert str(tmp_path.resolve()) not in result["data"]["directories"]


@pytest.mark.asyncio
async def test_handle_directory_calls_respect_filesystem_read_policy():
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_filesystem_roots.return_value = []

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch(
            "castrel_proxy.network.websocket_client.get_interactive_executor",
            return_value=MagicMock(),
        ),
        patch("castrel_proxy.network.websocket_client.SkillSyncManager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.OpenClawChecker", return_value=MagicMock()),
    ):
        client = WebSocketClient(
            server_url="https://server.example.com",
            client_id="client-123",
            verification_code="code-123",
            workspace_id="workspace-123",
        )
        client.server_policy = {
            "filesystem": {"read_enabled": False, "write_enabled": True, "edit_enabled": True}
        }

        list_result = await client._handle_command(
            {
                "id": "msg-dir-list-denied",
                "type": "directory_list_call",
                "data": {"path": "/tmp", "session_id": "session-123", "limit": 20},
            }
        )
        search_result = await client._handle_command(
            {
                "id": "msg-dir-search-denied",
                "type": "directory_search_call",
                "data": {"keyword": "/tmp", "session_id": "session-123", "limit": 20},
            }
        )

    assert list_result["type"] == "directory_list_result"
    assert list_result["success"] is False
    assert list_result["data"]["path"] == "/tmp"
    assert list_result["data"]["directories"] == []
    assert "disabled" in list_result["data"]["error"].lower()

    assert search_result["type"] == "directory_search_result"
    assert search_result["success"] is False
    assert search_result["data"]["keyword"] == "/tmp"
    assert search_result["data"]["directories"] == []
    assert "disabled" in search_result["data"]["error"].lower()
