"""Tests for websocket client command policy behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from castrel_proxy.core.executor import ExecutionResult
from castrel_proxy.network.websocket_client import WebSocketClient


@pytest.mark.asyncio
async def test_execute_local_command_skips_local_whitelist_when_yolo_enabled():
    """yolo=true should bypass only the local whitelist branch."""
    config = MagicMock()
    config.get_openclaw_check_enabled.return_value = False
    config.get_yolo_enabled.return_value = True

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=ExecutionResult(0, "ok", "", 0.01))

    with (
        patch("castrel_proxy.network.websocket_client.get_config", return_value=config),
        patch("castrel_proxy.network.websocket_client.get_mcp_manager", return_value=MagicMock()),
        patch("castrel_proxy.network.websocket_client.get_interactive_executor", return_value=MagicMock()),
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