# Security Policy

## Supported Versions

Currently supported versions with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in Castrel Bridge Proxy, please report it responsibly:

### How to Report

1. **Do NOT** create a public GitHub issue
2. Email security concerns to: security@example.com (replace with actual email)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Status Updates**: Weekly until resolved
- **Credit**: Security researchers will be credited (unless anonymous requested)

## Security Features

### Command Whitelist

All commands are validated against a whitelist before execution:

- Default whitelist includes common read-only commands
- Users can customize whitelist in `~/.castrel/whitelist.conf`
- Commands not in whitelist are rejected

### Path Validation

Document operations validate paths to prevent:

- Directory traversal attacks
- Access to system files outside allowed paths
- Symlink-based attacks

### Authentication

- Client-server authentication via verification codes
- Unique client ID based on machine characteristics
- Workspace isolation

### Secure Communication

- Support for WSS (WebSocket Secure)
- HTTPS for API endpoints
- No credentials stored in plain text

### Rate Limiting

Command execution includes:

- Timeout controls (default: 5 minutes)
- Resource limits
- Session-based isolation

## Best Practices

### For Users

1. **Use HTTPS/WSS**: Always use secure connections in production
2. **Minimal Whitelist**: Only allow commands you need
3. **Regular Updates**: Keep castrel-proxy updated
4. **Review Logs**: Monitor `~/.castrel/*/terminal.log` regularly
5. **Secure Codes**: Never share verification codes

### For Operators

1. **Network Isolation**: Run on isolated networks when possible
2. **Access Control**: Implement proper server-side authentication
3. **Audit Logging**: Enable comprehensive logging
4. **Regular Backups**: Backup configuration files
5. **Principle of Least Privilege**: Run with minimal required permissions

## Known Limitations

- Commands execute with user permissions of the running process
- No built-in rate limiting (implement server-side)
- Logs stored locally may contain sensitive information

## Security Updates

Security updates are released as patch versions. Subscribe to:

- GitHub Security Advisories
- Release notifications
- Security mailing list (if available)

## Responsible Disclosure

We follow responsible disclosure practices:

1. Vulnerabilities are fixed before public disclosure
2. Security advisories published after fixes are available
3. CVEs assigned for significant vulnerabilities
4. Credit given to researchers (with permission)

## Security Checklist

Before deploying to production:

- [ ] Use HTTPS/WSS connections
- [ ] Configure minimal command whitelist
- [ ] Review MCP service permissions
- [ ] Set up log monitoring
- [ ] Test authentication flow
- [ ] Verify firewall rules
- [ ] Enable audit logging
- [ ] Document security procedures

## Contact

For security concerns: security@example.com

For general issues: https://github.com/castrel-ai/castrel-proxy/issues
