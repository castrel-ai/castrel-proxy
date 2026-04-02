import asyncio

import aiohttp

from castrel_proxy.network.websocket_client import WebSocketClient


class DummyResponse:
    def __init__(self, status: int = 200, body: str = '{"status":"success"}'):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body


class DummyRequestContext:
    def __init__(self, response: DummyResponse):
        self.response = response

    async def __aenter__(self) -> DummyResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class DummyClientSession:
    def __init__(self, recorder: dict):
        self.recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, **kwargs):
        self.recorder["url"] = url
        self.recorder["kwargs"] = kwargs
        return DummyRequestContext(DummyResponse())


def test_http_proxy_is_blocked_when_policy_disables_it():
    client = WebSocketClient(
        server_url="http://localhost:8000",
        client_id="client-1",
        verification_code="code",
        workspace_id="ws-1",
    )
    client.server_policy = {"http": {"enabled": False, "allow_hosts": []}}

    result = asyncio.run(
        client._execute_http_proxy(
            message_id="msg-1",
            session_id="session-1",
            method="GET",
            url="http://prometheus.internal:9090/api/v1/labels",
            headers={},
            params={},
            body=None,
            verify_ssl=True,
            timeout=10,
        )
    )

    assert result["success"] is False
    assert "disabled" in result["data"]["error"]


def test_http_proxy_passes_ssl_flag_and_params(monkeypatch):
    recorder: dict = {}

    monkeypatch.setattr(aiohttp, "ClientSession", lambda: DummyClientSession(recorder))

    client = WebSocketClient(
        server_url="http://localhost:8000",
        client_id="client-1",
        verification_code="code",
        workspace_id="ws-1",
    )
    client.server_policy = {"http": {"enabled": True, "allow_hosts": ["prometheus.internal:9090"]}}

    result = asyncio.run(
        client._execute_http_proxy(
            message_id="msg-2",
            session_id="session-1",
            method="GET",
            url="https://prometheus.internal:9090/api/v1/labels",
            headers={"Authorization": "Bearer token"},
            params={"match[]": ["up", "process_start_time_seconds"]},
            body=None,
            verify_ssl=False,
            timeout=10,
        )
    )

    assert result["success"] is True
    assert recorder["url"] == "https://prometheus.internal:9090/api/v1/labels"
    assert recorder["kwargs"]["ssl"] is False
    assert recorder["kwargs"]["params"] == {"match[]": ["up", "process_start_time_seconds"]}
