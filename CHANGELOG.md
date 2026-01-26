# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Background daemon mode**: Bridge can now run as a background process (Unix/macOS only)
  - Automatic PID file management at `~/.castrel/castrel-proxy.pid`
  - Log output redirected to `~/.castrel/castrel-proxy.log`
  - Graceful shutdown handling (SIGTERM, SIGINT)
  - Process status checking and management
- **Enhanced `stop` command**: Now properly stops background daemon processes
- **Enhanced `status` command**: Shows actual running status with PID information
- **Enhanced `logs` command**: 
  - View last N lines of logs with `--lines`
  - Follow logs in real-time with `--follow`
  - Reads from daemon log file

### Changed
- **Breaking**: `castrel-proxy start` now defaults to background mode instead of foreground mode
  - Use `--foreground` or `-f` flag to run in foreground mode
  - Background mode only supported on Unix/macOS (not Windows)
  - Example: `castrel-proxy start --foreground` to run in foreground
- Logging in daemon mode redirects to file instead of stdout/stderr

### Fixed
- Enhanced MCP configuration validation to exit immediately on invalid configuration
- Added strict validation for required `transport` field in MCP server configuration
- Improved error messages for MCP configuration errors