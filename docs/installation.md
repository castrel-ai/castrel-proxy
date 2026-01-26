# Installation Guide

This guide covers various methods to install Castrel Bridge Proxy.

## Requirements

- Python >= 3.10
- pip or uv package manager

## Installation Methods

### Method 1: Install from PyPI (Recommended)

```bash
pip install castrel-proxy
```

Or using uv:

```bash
uv pip install castrel-proxy
```

### Method 2: Install from Source

```bash
# Clone the repository
git clone https://github.com/castrel-ai/castrel-bridge-proxy.git
cd castrel-bridge-proxy

# Install in development mode
pip install -e .
```

### Method 3: Install from GitHub

```bash
pip install git+https://github.com/castrel-ai/castrel-bridge-proxy.git
```

## Verify Installation

After installation, verify that the CLI is available:

```bash
castrel-proxy --help
```

You should see output showing available commands.

## Next Steps

After installation:

1. [Configure your bridge](configuration.md)
2. [Pair with server](quickstart.md)
3. [Set up MCP services](mcp-integration.md) (optional)

## Upgrading

To upgrade to the latest version:

```bash
pip install --upgrade castrel-proxy
```

## Uninstallation

To remove castrel-proxy:

```bash
pip uninstall castrel-proxy
```

Note: This will not remove your configuration files in `~/.castrel/`. To remove those:

```bash
rm -rf ~/.castrel
```

## Troubleshooting

### Command not found

If `castrel-proxy` command is not found after installation:

1. Check if Python scripts directory is in PATH:
   ```bash
   python -m site --user-base
   ```

2. Add to PATH (Linux/Mac):
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

### Permission errors

If you encounter permission errors during installation:

```bash
# Install for current user only
pip install --user castrel-proxy
```

### Python version issues

Check your Python version:

```bash
python --version
```

If you have multiple Python versions, specify pip3:

```bash
pip3 install castrel-proxy
```
