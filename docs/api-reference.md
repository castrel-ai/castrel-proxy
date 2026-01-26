# API Reference

Complete API reference for Castrel Bridge Proxy modules.

## Core Modules

### `castrel_proxy.core.config`

Configuration management module.

#### `Config`

```python
class Config:
    """Configuration management class"""
    
    def __init__(self, config_dir: Optional[Path] = None)
    def save(self, server_url: str, verification_code: str, 
             client_id: str, workspace_id: str) -> None
    def load(self) -> dict
    def exists(self) -> bool
    def delete(self) -> None
    def get_server_url(self) -> str
    def get_verification_code(self) -> str
    def get_client_id(self) -> str
    def get_workspace_id(self) -> str
    def get_paired_at(self) -> Optional[str]
```

#### `get_config()`

Get global configuration instance.

```python
def get_config() -> Config
```

### `castrel_proxy.core.client_id`

Client identification module.

#### `get_client_id()`

Generate unique client identifier based on machine characteristics.

```python
def get_client_id() -> str
```

Returns a 16-character hexadecimal string that is consistent for the same machine.

#### `get_machine_metadata()`

Get detailed machine metadata.

```python
def get_machine_metadata() -> Dict[str, str]
```

Returns dictionary with:
- `hostname`: Machine hostname
- `mac_address`: MAC address
- `os`: Operating system (Windows/Linux/Darwin)
- `os_version`: OS version
- `architecture`: Machine architecture (x86_64, arm64, etc.)
- `python_version`: Python version
- `platform`: Platform information

### `castrel_proxy.core.executor`

Command execution module.

#### `ExecutionResult`

```python
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    
    def to_dict(self) -> Dict
```

#### `CommandExecutor`

```python
class CommandExecutor:
    def __init__(self, session_id: str, working_dir: Optional[str] = None, 
                 timeout: float = 300.0)
    async def execute(self, command: str, cwd: Optional[str] = None) -> ExecutionResult
```

## Network Modules

### `castrel_proxy.network.api_client`

HTTP API client module.

#### Exceptions

```python
class APIError(Exception): pass
class PairingError(APIError): pass
class NetworkError(APIError): pass
```

#### `APIClient`

```python
class APIClient:
    def __init__(self, timeout: float = 10.0)
    def verify_pairing(self, server_url: str, verification_code: str,
                       client_id: str, workspace_id: str) -> Dict[str, any]
    def test_connection(self, server_url: str) -> bool
```

#### `get_api_client()`

Get global API client instance.

```python
def get_api_client() -> APIClient
```

### `castrel_proxy.network.websocket_client`

WebSocket client module.

#### `WebSocketClient`

```python
class WebSocketClient:
    def __init__(self, server_url: str, client_id: str, 
                 verification_code: str, workspace_id: str,
                 reconnect_interval: float = 5.0)
    async def connect(self) -> bool
    async def disconnect(self)
    async def run(self)
    async def stop(self)
```

## Core Modules

### `castrel_proxy.core.daemon`

Daemon process management module.

#### `DaemonManager`

```python
class DaemonManager:
    def __init__(self, pid_file: Path, log_file: Path)
    def daemonize(self) -> None  # Raises RuntimeError if already running
    def get_pid(self) -> Optional[int]
    def is_running(self) -> bool
    def stop(self) -> bool
```

**Methods**:
- `daemonize()`: Fork process and run in background (Unix/macOS only)
- `get_pid()`: Get PID from PID file
- `is_running()`: Check if daemon process is running
- `stop()`: Stop daemon process gracefully

**Error Handling**:
- `daemonize()`: Raises `RuntimeError` if daemon is already running
- Automatically cleans up PID files on exit
- Handles SIGTERM and SIGINT signals gracefully

#### `get_daemon_manager()`

Get daemon manager instance with default paths.

```python
def get_daemon_manager() -> DaemonManager
```

**Default Paths**:
- PID file: `~/.castrel/castrel-proxy.pid`
- Log file: `~/.castrel/castrel-proxy.log`

## MCP Modules

### `castrel_proxy.mcp.manager`

MCP service management module.

#### `MCPManager`

```python
class MCPManager:
    def __init__(self, config_file: Optional[Path] = None)
    def load_config(self) -> Dict
    def get_server_list(self) -> List[Dict]
    async def connect_all(self) -> int  # Raises SystemExit on configuration error
    async def get_all_tools(self) -> Dict[str, List[Dict]]  # Raises SystemExit on error
    async def disconnect_all(self)
```

**Error Handling**:
- `connect_all()`: Exits with code 1 if configuration is invalid or connection fails
- `get_all_tools()`: Exits with code 1 if client is not initialized, no tools retrieved, or retrieval fails

#### `convert_config_to_langchain_format()`

Convert MCP configuration to langchain-mcp-adapters format with strict validation.

```python
def convert_config_to_langchain_format(config_data: dict) -> dict
```

**Raises**:
- `ValueError`: When configuration is invalid (missing required keys or unsupported transport type)

**Supported Transport Types**:
- `stdio`: Requires `command` field, optional `args` and `env`
- `http`: Requires `url` field
- `sse`, `websocket`: Not yet supported (will raise ValueError)

#### `get_mcp_manager()`

Get global MCP manager instance.

```python
def get_mcp_manager() -> MCPManager
```

## Operations Modules

### `castrel_proxy.operations.document`

Document operations module.

#### Functions

```python
def read_document(file_path: str, encoding: Optional[str] = None) -> Dict[str, Any]
def write_document(file_path: str, content: str, 
                   encoding: str = "utf-8", create_dirs: bool = True) -> Dict[str, Any]
def edit_document(file_path: str, operation: str, new_content: str,
                  old_content: Optional[str] = None, 
                  encoding: Optional[str] = None) -> Dict[str, Any]
```

**Operation types for `edit_document`**:
- `replace`: Replace old content with new content
- `append`: Append new content to end of file
- `prepend`: Prepend new content to beginning of file

## Security Modules

### `castrel_proxy.security.whitelist`

Command whitelist module.

#### Functions

```python
def load_whitelist() -> Set[str]
def is_command_allowed(full_command: str) -> Tuple[bool, List[str]]
def get_whitelist_file_path() -> str
def init_whitelist_file() -> str
def get_default_whitelist() -> List[str]
```

## CLI Module

### `castrel_proxy.cli.commands`

Command-line interface module.

#### Commands

All commands are accessible via `castrel-proxy` command:

```bash
castrel-proxy pair <code> <server_url>
castrel-proxy start [--daemon | --foreground]  # Runs in background by default
castrel-proxy stop
castrel-proxy status
castrel-proxy config
castrel-proxy unpair
castrel-proxy mcp-list
castrel-proxy mcp-sync
castrel-proxy logs [--lines N] [--follow]
```

## Usage Examples

### Basic Usage

```python
from castrel_proxy import get_config, get_client_id

# Get configuration
config = get_config()
config_data = config.load()
print(f"Server: {config_data['server_url']}")

# Get client ID
client_id = get_client_id()
print(f"Client ID: {client_id}")
```

### Execute Command

```python
from castrel_proxy.core.executor import CommandExecutor

# Create executor
executor = CommandExecutor(session_id="test-session")

# Execute command
result = await executor.execute("ls -la")
print(f"Exit code: {result.exit_code}")
print(f"Output: {result.stdout}")
```

### Check Command Whitelist

```python
from castrel_proxy.security.whitelist import is_command_allowed

# Check if command is allowed
allowed, blocked = is_command_allowed("ls -la && cat file.txt")
if allowed:
    print("Command is allowed")
else:
    print(f"Blocked commands: {blocked}")
```

### MCP Integration

```python
from castrel_proxy.mcp.manager import get_mcp_manager

# Get MCP manager
mcp_manager = get_mcp_manager()

# Connect to services
count = await mcp_manager.connect_all()
print(f"Connected to {count} services")

# Get tools
tools = await mcp_manager.get_all_tools()
print(f"Available tools: {tools}")
```

## Error Handling

### Exception Hierarchy

```
Exception
├── ConfigError
├── DocumentOperationError
└── APIError
    ├── PairingError
    └── NetworkError
```

### Example

```python
from castrel_proxy import get_config, ConfigError

try:
    config = get_config()
    data = config.load()
except ConfigError as e:
    print(f"Configuration error: {e}")
    # Handle error...
```

## Type Hints

All modules include comprehensive type hints. Use mypy for type checking:

```bash
mypy src/castrel_proxy/
```

## Logging

All modules use Python's standard logging module:

```python
import logging

# Set log level
logging.basicConfig(level=logging.DEBUG)
```

Log levels:
- `DEBUG`: Detailed diagnostic information
- `INFO`: General information (default)
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

## Constants

### File Size Limits

```python
# operations/document.py
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
```

### Timeouts

```python
# core/executor.py
DEFAULT_TIMEOUT = 300.0  # seconds

# network/api_client.py
DEFAULT_API_TIMEOUT = 10.0  # seconds

# network/websocket_client.py
HEARTBEAT_INTERVAL = 30.0  # seconds
```

## See Also

- [Configuration Guide](configuration.md)
- [Installation Guide](installation.md)
- [Security Policy](../SECURITY.md)
