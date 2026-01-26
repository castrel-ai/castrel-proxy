# Daemon Mode Guide

This guide explains how to use Castrel Bridge Proxy in background daemon mode.

## Overview

Background daemon mode allows the bridge to run as a system service, automatically managing:
- Process forking and detachment
- PID file management
- Log file redirection
- Signal handling for graceful shutdown

## Platform Support

- ✅ **Unix/Linux**: Full support
- ✅ **macOS**: Full support
- ❌ **Windows**: Not supported (use `--foreground` mode instead)

## Basic Usage

### Start in Background (Default)

```bash
castrel-proxy start
```

Expected output:
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

### Start in Foreground

```bash
castrel-proxy start --foreground
# or
castrel-proxy start -f
```

## Managing the Daemon

### Check Status

```bash
castrel-proxy status
```

Example output:
```
=== Bridge Status ===
Pairing status: Paired
Server: https://server.example.com
Client ID: a1b2c3d4e5f6
Workspace ID: default
Paired at: 2025-01-26T10:30:00Z
Running status: Running (PID: 12345)
PID file: /Users/username/.castrel/castrel-proxy.pid
Log file: /Users/username/.castrel/castrel-proxy.log
Hint: Use 'castrel-proxy logs -f' to follow logs
```

### Stop the Daemon

```bash
castrel-proxy stop
```

Expected output:
```
Stopping bridge (PID: 12345)...
✓ Bridge stopped
```

### View Logs

View last 50 lines (default):
```bash
castrel-proxy logs
```

View last 100 lines:
```bash
castrel-proxy logs -n 100
```

Follow logs in real-time:
```bash
castrel-proxy logs -f
```

Press `Ctrl+C` to stop following logs.

## File Locations

By default, daemon files are stored in `~/.castrel/`:

- **PID file**: `~/.castrel/castrel-proxy.pid`
  - Contains the process ID of the running daemon
  - Automatically created on start
  - Automatically removed on clean exit

- **Log file**: `~/.castrel/castrel-proxy.log`
  - Contains all daemon output (stdout and stderr)
  - Appends on each run
  - Uses standard logging format with timestamps

## How It Works

### Daemonization Process

1. **Pre-flight checks**:
   - Verify not already running (checks PID file)
   - Validate configuration

2. **First fork**:
   - Parent process exits
   - Child becomes session leader

3. **Environment setup**:
   - Change working directory to `/`
   - Set umask to 0
   - Create new session (setsid)

4. **Second fork**:
   - Parent process exits
   - Child becomes true daemon (no controlling terminal)

5. **File descriptor handling**:
   - Redirect stdin to `/dev/null`
   - Redirect stdout to log file
   - Redirect stderr to log file

6. **PID file creation**:
   - Write daemon PID to file
   - Register cleanup on exit

7. **Signal handling**:
   - Register SIGTERM handler (graceful shutdown)
   - Register SIGINT handler (graceful shutdown)

### Stopping the Daemon

When you run `castrel-proxy stop`:

1. Read PID from PID file
2. Check if process is running (send signal 0)
3. Send SIGTERM for graceful shutdown
4. Wait up to 5 seconds for process to exit
5. If still running, send SIGKILL (force kill)
6. Clean up PID file

## Troubleshooting

### Already Running Error

**Error**: `✗ Bridge is already running with PID 12345`

**Solution**: Stop the existing daemon first:
```bash
castrel-proxy stop
castrel-proxy start
```

### Stale PID File

If the daemon crashed or was forcefully killed, you may have a stale PID file.

**Check status**:
```bash
castrel-proxy status
```

**Clean up** (if not running):
```bash
castrel-proxy stop  # Automatically cleans up stale PID files
```

Or manually:
```bash
rm ~/.castrel/castrel-proxy.pid
```

### Log File Growing Too Large

The log file continuously appends. To manage size:

**View and truncate**:
```bash
# Save last 1000 lines
tail -n 1000 ~/.castrel/castrel-proxy.log > ~/.castrel/castrel-proxy.log.tmp
mv ~/.castrel/castrel-proxy.log.tmp ~/.castrel/castrel-proxy.log

# Restart daemon to use new file
castrel-proxy stop
castrel-proxy start
```

**Archive old logs**:
```bash
mv ~/.castrel/castrel-proxy.log ~/.castrel/castrel-proxy.log.$(date +%Y%m%d)
castrel-proxy stop
castrel-proxy start
```

### Permission Issues

If you get permission errors:

1. Check directory permissions:
```bash
ls -la ~/.castrel/
```

2. Ensure you own the files:
```bash
chown -R $USER:$USER ~/.castrel/
```

### Daemon Not Stopping

If `castrel-proxy stop` fails:

1. Get the PID:
```bash
cat ~/.castrel/castrel-proxy.pid
```

2. Manually kill:
```bash
kill -TERM <PID>  # Graceful
# or
kill -9 <PID>     # Force
```

3. Clean up:
```bash
rm ~/.castrel/castrel-proxy.pid
```

## Advanced Usage

### Custom Log Levels

Set log level via environment variable before starting:

```bash
export CASTREL_LOG_LEVEL=DEBUG
castrel-proxy start
```

### Running as System Service

For production, consider creating a systemd service (Linux) or launchd service (macOS).

#### Systemd Service Example (Linux)

Create `/etc/systemd/system/castrel-proxy.service`:

```ini
[Unit]
Description=Castrel Bridge Proxy
After=network.target

[Service]
Type=forking
User=yourusername
ExecStart=/usr/local/bin/castrel-proxy start
ExecStop=/usr/local/bin/castrel-proxy stop
PIDFile=/home/yourusername/.castrel/castrel-proxy.pid
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable castrel-proxy
sudo systemctl start castrel-proxy
sudo systemctl status castrel-proxy
```

#### Launchd Service Example (macOS)

Create `~/Library/LaunchAgents/com.castrel.proxy.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.castrel.proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/castrel-proxy</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yourusername/.castrel/castrel-proxy.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yourusername/.castrel/castrel-proxy.log</string>
</dict>
</plist>
```

Load and start:
```bash
launchctl load ~/Library/LaunchAgents/com.castrel.proxy.plist
launchctl start com.castrel.proxy
```

## Best Practices

1. **Monitor logs regularly**: Use `castrel-proxy logs -f` to watch for errors
2. **Check status after start**: Verify daemon started successfully
3. **Rotate logs**: Set up log rotation to manage file size
4. **Use system services**: For production, use systemd/launchd instead of manual daemon
5. **Graceful restarts**: Always use `stop` then `start` instead of killing process

## Security Considerations

1. **File Permissions**: PID and log files are created with user-only write permissions
2. **Process Ownership**: Daemon runs as the user who started it
3. **Signal Handling**: Only responds to SIGTERM and SIGINT for controlled shutdown
4. **No Privilege Escalation**: Does not require root/admin privileges

## See Also

- [Installation Guide](installation.md)
- [Configuration Guide](configuration.md)
- [Quickstart Guide](quickstart.md)
