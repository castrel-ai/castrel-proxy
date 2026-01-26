# Quick Start Guide

Get started with Castrel Bridge Proxy in 5 minutes.

## Prerequisites

- Python 3.10 or higher
- Server URL and verification code from your server administrator

## Step 1: Installation

```bash
pip install castrel-proxy
```

## Step 2: Pair with Server

You'll need:
- Verification code (from server administrator)
- Server URL

```bash
castrel-proxy pair <verification_code> <server_url>
```

**Example**:
```bash
castrel-proxy pair eyJ0cyI6MTczNTA4ODQwMCwid2lkIjoiZGVmYXVsdCIsInJhbmQiOiIxMjM0NTYifQ https://server.example.com
```

**Expected output**:
```
Parsing verification code...
✓ Verification code parsed successfully
  Workspace ID: default

Generating client identifier...
Client ID: a1b2c3d4e5f6

Connecting to server: https://server.example.com
...
✓ Pairing successful!
Configuration saved to: /Users/username/.castrel/config.yaml
```

## Step 3: Start the Bridge

```bash
# Background mode (default, Unix/macOS only)
castrel-proxy start

# Foreground mode
castrel-proxy start --foreground
```

**Expected output** (background mode):
```
=== Starting Bridge Service ===
Server: https://server.example.com
Client ID: a1b2c3d4e5f6
Workspace ID: default

Starting bridge in background...
PID file: /Users/username/.castrel/castrel-proxy.pid
Log file: /Users/username/.castrel/castrel-proxy.log
✓ Bridge started in background
PID: 12345
Hint: Use 'castrel-proxy logs -f' to follow logs
Hint: Use 'castrel-proxy stop' to stop service
```

**Expected output** (foreground mode):
```
=== Starting Bridge Service ===
Server: https://server.example.com
Client ID: a1b2c3d4e5f6
Workspace ID: default

Running in foreground mode...
Connecting to server...
Hint: Press Ctrl+C to stop service

[Logs will appear here as commands are executed]
```

**Note**: Background mode is only supported on Unix/macOS systems. Windows users must use `--foreground` flag.

## Step 4: Verify Connection

In another terminal, check status:

```bash
castrel-proxy status
```

**Expected output**:
```
=== Bridge Status ===
Pairing status: Paired
Server: https://server.example.com
Client ID: a1b2c3d4e5f6
Workspace ID: default
Paired at: 2025-01-26T10:30:00Z
```

## Optional: Configure MCP Services

If you want to use MCP integration:

### 1. Create MCP Configuration

```bash
# Copy example configuration
cp examples/mcp.json.example ~/.castrel/mcp.json

# Edit configuration
nano ~/.castrel/mcp.json
```

### 2. Configure Services

Example for filesystem access:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"],
      "env": {}
    }
  }
}
```

### 3. Sync MCP Tools

```bash
castrel-proxy mcp-sync
```

### 4. Verify MCP Services

```bash
castrel-proxy mcp-list
```

## Common Commands

```bash
# View configuration
castrel-proxy config

# Check status
castrel-proxy status

# Start bridge in background (default)
castrel-proxy start

# Start bridge in foreground
castrel-proxy start --foreground

# Stop background bridge
castrel-proxy stop

# View logs
castrel-proxy logs

# Follow logs in real-time
castrel-proxy logs -f

# List MCP services
castrel-proxy mcp-list

# Sync MCP tools
castrel-proxy mcp-sync

# Unpair from server
castrel-proxy unpair
```

## What's Next?

- Learn about [Configuration](configuration.md)
- Explore [MCP Integration](mcp-integration.md)
- Read [API Reference](api-reference.md)
- Understand [Security](../SECURITY.md)

## Troubleshooting

### Pairing fails

Check:
1. Server URL is correct and accessible
2. Verification code is valid
3. Network connection is working

### Can't connect to server

Check:
1. Server is running
2. No firewall blocking connection
3. Configuration is correct: `castrel-proxy config`

### Commands not executing

Check:
1. Command is in whitelist: `cat ~/.castrel/whitelist.conf`
2. Check logs: `~/.castrel/*/terminal.log`

## Getting Help

- [Documentation](../README.md)
- [GitHub Issues](https://github.com/castrel-ai/castrel-bridge-proxy/issues)
- [Contributing Guide](../CONTRIBUTING.md)
