# MCP Integration

Castrel Proxy can optionally connect to local MCP (Model Context Protocol) servers and synchronize the available tools to the Castrel server. The server can then request tool executions through the proxy.

## How it works

- The proxy reads an MCP config file from `~/.castrel/mcp.json`
- On startup (`castrel-proxy start`), the proxy connects to all configured MCP servers
- When the server sends an `mcp_tool_call` over the WebSocket, the proxy executes the corresponding MCP tool locally and returns the result
- MCP tools metadata can be uploaded to the server during pairing, or later via manual sync

## Configuration file

Create `~/.castrel/mcp.json` with a `mcpServers` object. Each entry must include a `transport` key.

Supported transports:

- `stdio`: starts an MCP server process locally
- `http`: connects to an MCP server over HTTP
- `sse`: connects to an MCP server via Server-Sent Events

Example:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "env": {}
    },
    "weather": {
      "transport": "http",
      "url": "http://localhost:8000/mcp"
    },
    "internal-sse": {
      "transport": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

More examples: `examples/mcp.json.example`.

## CLI commands

### List configured MCP servers

```bash
castrel-proxy mcp-list
```

This prints what the proxy sees in `~/.castrel/mcp.json`.

### Sync tool metadata to server

```bash
castrel-proxy mcp-sync
```

This command:

- Loads pairing info from `~/.castrel/config.yaml`
- Connects to all configured MCP servers
- Retrieves all tools from each server
- Sends the tool list to the Castrel server

### Pairing-time sync

During `castrel-proxy pair`, the proxy will also attempt to load MCP servers and send tool metadata to the server. If no MCP servers are configured, it will still pair successfully and skip MCP registration.

## Tool naming and routing

The Castrel server calls a tool with:

- `server_name`: the key under `mcpServers` (e.g. `filesystem`)
- `tool_name`: the MCP tool name exposed by that server

The proxy resolves tools by fetching tools from the MCP server and matching by `tool.name`.

## Troubleshooting

### “MCP configuration file does not exist”

Create `~/.castrel/mcp.json` (or copy from `examples/mcp.json.example`), then run:

```bash
castrel-proxy mcp-list
castrel-proxy mcp-sync
```

### “Missing 'transport' key” / invalid configuration

Each server entry under `mcpServers` must include:

- `transport`: one of `stdio`, `http`, `sse`

For `stdio`, you must also include:

- `command` (string)

For `http`/`sse`, you must include:

- `url` (string)

### Tool not found

If the server requests a tool that is not available, the proxy returns an `mcp_tool_result` with `success=false`. Re-run:

```bash
castrel-proxy mcp-sync
```

and confirm the tool exists in the tool list printed in the sync output.

