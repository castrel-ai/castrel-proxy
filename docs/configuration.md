# Configuration Guide

This guide explains how to configure Castrel Bridge Proxy.

## Configuration Files

Castrel Bridge Proxy uses several configuration files:

### 1. Bridge Configuration

**Location**: `~/.castrel/config.yaml`

This file is created automatically when you pair with a server.

**Example**:
```yaml
server_url: "https://server.example.com"
verification_code: "ABC123"
client_id: "a1b2c3d4e5f6"
workspace_id: "default"
paired_at: "2025-01-26T10:30:00Z"
```

**Fields**:
- `server_url`: The server URL to connect to
- `verification_code`: Verification code for authentication
- `client_id`: Unique identifier for this client machine
- `workspace_id`: Workspace identifier
- `paired_at`: Timestamp when pairing occurred

### 2. MCP Configuration

**Location**: `~/.castrel/mcp.json`

Configure MCP (Model Context Protocol) services. This is optional.

**Example**:
```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/Documents"],
      "env": {}
    },
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "your-token"
      }
    },
    "weather": {
      "transport": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

See `examples/mcp.json.example` for more examples.

### 3. Command Whitelist

**Location**: `~/.castrel/whitelist.conf`

Configure which commands are allowed to execute. This file is created automatically with sensible defaults when you first pair.

**Example**:
```
# Castrel Command Whitelist
# One command per line, # for comments

ls
cat
git
python
kubectl
docker
```

**Security Note**: Only commands in this whitelist can be executed remotely.

## Configuration Management Commands

### View Current Configuration

```bash
castrel-proxy config
```

### Check Status

```bash
castrel-proxy status
```

### Unpair (Remove Configuration)

```bash
castrel-proxy unpair
```

## MCP Configuration

### List Configured Services

```bash
castrel-proxy mcp-list
```

### Sync MCP Tools to Server

```bash
castrel-proxy mcp-sync
```

## Environment Variables

Castrel Bridge Proxy respects these environment variables:

- `CASTREL_CONFIG_DIR`: Override default config directory (default: `~/.castrel`)
- `CASTREL_LOG_LEVEL`: Set log level (DEBUG, INFO, WARNING, ERROR)

Example:
```bash
export CASTREL_CONFIG_DIR=/custom/path
export CASTREL_LOG_LEVEL=DEBUG
castrel-proxy start  # Runs in background by default
```

## Advanced Configuration

### Custom Session Directory

By default, session data is stored in `~/.castrel/<session_id>/`. You can specify a custom working directory when executing commands.

### Custom Timeout

The default command timeout is 300 seconds (5 minutes). This is configured server-side when sending commands.

## Security Best Practices

1. **Whitelist Commands**: Regularly review your whitelist configuration
2. **Secure Verification Codes**: Never share your verification codes
3. **Use HTTPS**: Always use `https://` URLs for production servers
4. **Review MCP Tools**: Understand what tools each MCP service exposes
5. **Monitor Logs**: Check `~/.castrel/<session_id>/terminal.log` for executed commands

## Troubleshooting

### Configuration Not Found

If you see "Configuration file does not exist":

```bash
# Pair with server first
castrel-proxy pair <code> <server_url>
```

### Invalid Configuration

If configuration is corrupted:

```bash
# Remove and re-pair
rm ~/.castrel/config.yaml
castrel-proxy pair <code> <server_url>
```

### MCP Services Not Working

Check configuration:

```bash
# List services
castrel-proxy mcp-list

# Verify JSON syntax
cat ~/.castrel/mcp.json | python -m json.tool
```
