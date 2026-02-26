# Castrel Proxy Docker Image

[![Docker Image Size](https://img.shields.io/docker/image-size/castrel/castrel-proxy/latest)](https://hub.docker.com/r/castrel/castrel-proxy)
[![Docker Pulls](https://img.shields.io/docker/pulls/castrel/castrel-proxy)](https://hub.docker.com/r/castrel/castrel-proxy)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Docker image for [Castrel Proxy](https://github.com/castrel-ai/castrel-proxy) - A lightweight remote command execution bridge client with MCP integration.

## Features

- Secure WebSocket-based remote command execution
- MCP (Model Context Protocol) integration
- Automatic reconnection support
- Command whitelist security
- Persistent configuration
- Optimized for production use with:
  - tini init system for proper signal handling
  - Health check for container orchestration
  - Non-root user for security
  - Multi-stage build for minimal image size (~350MB)

## Quick Start

### 1. Pair with Server

```bash
docker run --rm castrel/castrel-proxy pair <verification_code> <server_url>
```

Example:
```bash
docker run --rm castrel/castrel-proxy pair eyJ0cyI6MTczNTA4ODQwMCwid2lkIjoiZGVmYXVsdCIsInJhbmQiOiIxMjM0NTYifQ https://server.example.com
```

### 2. Run as Background Service

```bash
# Create persistent volume for configuration
docker volume create castrel-config

# Run paired client in background
docker run -d \
  --name castrel-proxy \
  --restart unless-stopped \
  -v castrel-config:/home/castrel/.castrel \
  castrel/castrel-proxy start --foreground
```

### 3. Check Status

```bash
docker exec castrel-proxy castrel-proxy status
```

### 4. View Logs

```bash
# Docker logs
docker logs castrel-proxy

# Application logs
docker exec castrel-proxy castrel-proxy logs -f
```

### 5. Stop Service

```bash
docker stop castrel-proxy
```

## Usage

### Available Commands

| Command | Description |
|---------|-------------|
| `pair` | Pair with server using verification code |
| `start` | Start bridge service |
| `stop` | Stop bridge service |
| `status` | Check bridge running status |
| `config` | View configuration |
| `logs` | View bridge logs |
| `mcp-list` | List configured MCP services |
| `mcp-sync` | Sync MCP tools to server |
| `unpair` | Unpair from server |

### Running Commands

```bash
# Show help
docker run --rm castrel/castrel-proxy --help

# Pair with server
docker run --rm castrel/castrel-proxy pair <code> <url>

# Start in foreground mode
docker run --rm castrel/castrel-proxy start --foreground

# Check status
docker run --rm -v castrel-config:/home/castrel/.castrel castrel/castrel-proxy status
```

## Configuration

### Persistent Configuration

Configuration is stored in `~/.castrel/` directory. Use a Docker volume to persist:

```bash
docker run -d \
  -v castrel-config:/home/castrel/.castrel \
  castrel/castrel-proxy start --foreground
```

### Configuration Files

| File | Path | Description |
|------|------|-------------|
| Main Config | `~/.castrel/config.yaml` | Pairing information and settings |
| MCP Config | `~/.castrel/mcp.json` | MCP service configurations |
| Whitelist | `~/.castrel/whitelist.conf` | Allowed commands |

### MCP Configuration Example

Mount your MCP configuration:

```bash
docker run -d \
  -v castrel-config:/home/castrel/.castrel \
  -v /path/to/mcp.json:/home/castrel/.castrel/mcp.json:ro \
  castrel/castrel-proxy start --foreground
```

Example `mcp.json`:
```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    }
  }
}
```

## Docker Compose

### Basic Setup

```yaml
version: '3.8'

services:
  castrel-proxy:
    image: castrel/castrel-proxy:latest
    container_name: castrel-proxy
    restart: unless-stopped
    volumes:
      - castrel-config:/home/castrel/.castrel
    command: start --foreground

volumes:
  castrel-config:
```

### With Host Network (for MCP local services)

```yaml
version: '3.8'

services:
  castrel-proxy:
    image: castrel/castrel-proxy:latest
    container_name: castrel-proxy
    restart: unless-stopped
    network_mode: host
    volumes:
      - castrel-config:/home/castrel/.castrel
      - /path/to/workspace:/workspace:ro
    environment:
      - PYTHONPATH=/app/src
    command: start --foreground

volumes:
  castrel-config:
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYTHONUNBUFFERED` | `1` | Unbuffered Python output |
| `PYTHONDONTWRITEBYTECODE` | `1` | Don't write .pyc files |
| `PYTHONPATH` | `/app/src` | Python module path |

## Health Check

The image includes a built-in health check:

```bash
docker inspect --format='{{.State.Health.Status}}' castrel-proxy
```

Health check configuration:
- Interval: 30s
- Timeout: 10s
- Start Period: 5s
- Retries: 3

## Build from Source

```bash
git clone https://github.com/castrel-ai/castrel-proxy.git
cd castrel-proxy
docker build -t castrel-proxy:local .
```

## Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `0.1.3` | Specific version |
| `main` | Latest from main branch |

## Architecture

Supported architectures:
- `amd64` (x86_64)
- `arm64` (aarch64)

## Security

- Runs as non-root user (`castrel`)
- No privileged access required
- Command execution controlled by whitelist
- Verification code-based pairing

## Troubleshooting

### Container exits immediately
Ensure you're pairing first and using `--foreground` flag:
```bash
docker run --rm -v castrel-config:/home/castrel/.castrel castrel/castrel-proxy start --foreground
```

### Configuration not persisting
Make sure to mount the config volume:
```bash
-v castrel-config:/home/castrel/.castrel
```

### Connection issues
Check network connectivity and server URL:
```bash
docker exec castrel-proxy castrel-proxy config
```

## Links

- [GitHub Repository](https://github.com/castrel-ai/castrel-proxy)
- [Documentation](https://github.com/castrel-ai/castrel-proxy#readme)
- [Issue Tracker](https://github.com/castrel-ai/castrel-proxy/issues)
- [PyPI Package](https://pypi.org/project/castrel-proxy/)

## License

MIT License - see [LICENSE](https://github.com/castrel-ai/castrel-proxy/blob/main/LICENSE) for details.