# Migration Guide

This document highlights user-facing changes across releases and how to migrate your local setup.

## What gets stored locally

Castrel Proxy stores configuration and logs under your home directory:

- `~/.castrel/config.yaml`: pairing info (server URL, verification code, client ID, workspace ID)
- `~/.castrel/whitelist.conf`: command whitelist used to gate local shell execution
- `~/.castrel/mcp.json`: optional MCP server configuration (if you use MCP integration)
- `~/.castrel/<session_id>/terminal.log`: per-session operation log for MCP and document operations

## If you upgrade and things break

### 1) Re-run pairing

If the server rejects your connection after upgrading, re-pair to refresh local configuration:

```bash
castrel-proxy pair <verification_code> <server_url>
```

This recreates/updates `~/.castrel/config.yaml` and (re)initializes the whitelist file if needed.

### 2) Check your whitelist

If remote command execution starts failing with “not in whitelist”, update:

`~/.castrel/whitelist.conf`

Add the required commands (one per line) and retry.

### 3) Validate MCP configuration

If you use MCP integration, ensure `~/.castrel/mcp.json` matches the current schema:

- Each server under `mcpServers` must include `transport`
- `stdio` requires `command`
- `http` / `sse` require `url`

Then re-sync:

```bash
castrel-proxy mcp-sync
```

## Version notes

If you introduce a breaking change, add a new section here describing:

- What changed
- Who is affected
- How to migrate (commands + config changes)

