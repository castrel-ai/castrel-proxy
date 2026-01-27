# Protocol Specification

This document describes the WebSocket message protocol used between the Castrel server and the Castrel Proxy (bridge client).

## WebSocket endpoint

The proxy connects to the server using:

`/api/v1/bridge/ws?client_id=<client_id>&workspace_id=<workspace_id>&verification_code=<verification_code>`

The proxy converts:

- `https://` → `wss://`
- `http://` → `ws://`

## Message envelope

Messages are JSON objects. Most messages share a common envelope:

```json
{
  "id": "string",
  "type": "string",
  "timestamp": 1730000000000,
  "data": {}
}
```

Notes:

- `id` is used to correlate request/response pairs.
- `timestamp` is typically milliseconds since epoch. Some message types may omit it.
- `data` shape depends on `type`.

## Server → Proxy message types

### `connected`

Sent by the server after the WebSocket is established.

```json
{
  "id": "string",
  "type": "connected",
  "timestamp": 1730000000000,
  "session_id": "string",
  "message": "string"
}
```

The proxy does not respond.

### `local_tool_call`

Request the proxy to execute a local shell command.

```json
{
  "id": "string",
  "type": "local_tool_call",
  "timestamp": 1730000000000,
  "data": {
    "command": "string",
    "args": ["string"],
    "cwd": "string",
    "timeout": 300,
    "session_id": "string"
  }
}
```

Important:

- `session_id` is required by the proxy to execute commands.
- Commands are validated against the local whitelist (see `~/.castrel/whitelist.conf`).

### `mcp_tool_call`

Request the proxy to execute an MCP tool locally.

```json
{
  "id": "string",
  "type": "mcp_tool_call",
  "timestamp": 1730000000000,
  "data": {
    "server_name": "string",
    "tool_name": "string",
    "arguments": {},
    "session_id": "string"
  }
}
```

Important:

- `session_id` is required by the proxy to execute MCP tools.
- `server_name` must match a configured MCP server name in `~/.castrel/mcp.json`.

### `doc_read_call`

Request the proxy to read a local file.

```json
{
  "id": "string",
  "type": "doc_read_call",
  "timestamp": 1730000000000,
  "data": {
    "file_path": "string",
    "encoding": "string",
    "session_id": "string"
  }
}
```

### `doc_write_call`

Request the proxy to write a local file.

```json
{
  "id": "string",
  "type": "doc_write_call",
  "timestamp": 1730000000000,
  "data": {
    "file_path": "string",
    "content": "string",
    "encoding": "utf-8",
    "create_dirs": true,
    "session_id": "string"
  }
}
```

### `doc_edit_call`

Request the proxy to edit a local file using a simple operation.

```json
{
  "id": "string",
  "type": "doc_edit_call",
  "timestamp": 1730000000000,
  "data": {
    "file_path": "string",
    "operation": "replace|append|prepend",
    "new_content": "string",
    "old_content": "string",
    "encoding": "string",
    "session_id": "string"
  }
}
```

`old_content` is only required for `replace`.

### `ping` / `pong`

The server can send `ping`. The proxy replies with `pong`:

```json
{ "id": "string", "type": "pong" }
```

The proxy also sends periodic heartbeats (see below).

## Proxy → Server message types

### `local_tool_result`

Response to `local_tool_call`.

```json
{
  "id": "string",
  "type": "local_tool_result",
  "success": true,
  "data": {
    "exit_code": 0,
    "stdout": "string",
    "stderr": "string",
    "execution_time": 0.12
  }
}
```

When blocked by the whitelist, the proxy returns `success=false` with `exit_code=-3` and a message that points to the whitelist file path.

### `mcp_tool_result`

Response to `mcp_tool_call`.

```json
{
  "id": "string",
  "type": "mcp_tool_result",
  "success": true,
  "data": {
    "server_name": "string",
    "tool_name": "string",
    "result": {}
  }
}
```

On error, `success=false` and `data.error` is populated.

### `doc_read_result`

Response to `doc_read_call`.

```json
{
  "id": "string",
  "type": "doc_read_result",
  "success": true,
  "data": {
    "content": "string",
    "encoding": "string",
    "size": 123,
    "error": null
  }
}
```

### `doc_write_result`

Response to `doc_write_call`.

```json
{
  "id": "string",
  "type": "doc_write_result",
  "success": true,
  "data": {
    "path": "string",
    "size": 123,
    "error": null
  }
}
```

### `doc_edit_result`

Response to `doc_edit_call`.

```json
{
  "id": "string",
  "type": "doc_edit_result",
  "success": true,
  "data": {
    "operation": "replace|append|prepend",
    "path": "string",
    "size": 123,
    "error": null
  }
}
```

### `ping`

The proxy sends its own heartbeat periodically:

```json
{
  "id": "string",
  "type": "ping",
  "timestamp": 1730000000000
}
```

The server may respond with `pong`.

### `error`

For unknown message types received from the server, the proxy may reply:

```json
{
  "id": "string",
  "type": "error",
  "error": "Unknown message type: ..."
}
```

## Session logging

For MCP tool calls and document operations, the proxy writes a per-session log file:

`~/.castrel/<session_id>/terminal.log`

This is intended to help debugging and auditing remote operations.

