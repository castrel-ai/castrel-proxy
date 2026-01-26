# Contributing to Castrel Bridge Proxy

Thank you for your interest in contributing to Castrel Bridge Proxy! This document provides guidelines and instructions for contributing.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](../../issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (OS, Python version, etc.)
   - Relevant logs or error messages

### Suggesting Features

1. Check existing feature requests in [Issues](../../issues)
2. Create a new issue with:
   - Clear description of the feature
   - Use cases and benefits
   - Possible implementation approach

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Write or update tests as needed
5. Update documentation if required
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to your branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## Development Setup

### Prerequisites

- Python >= 3.10
- pip or uv for package management

### Setup Steps

```bash
# Clone the repository
git clone https://github.com/castrel-ai/castrel-proxy.git
cd castrel-proxy

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate

# Install dependencies
pip install -e .

# Install development dependencies
pip install -e ".[dev]"
```

## Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for all public functions and classes
- Keep functions focused and single-purpose
- Maximum line length: 100 characters

### Code Formatting

```bash
# Format code
black src/

# Check with flake8
flake8 src/

# Type checking
mypy src/
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=castrel_proxy

# Run specific test file
pytest tests/test_core.py
```

## Documentation

- Update README.md for user-facing changes
- Add docstrings to all new functions/classes
- Update examples if adding new features
- Keep docs/ directory up to date

## Commit Messages

Follow conventional commits format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Example:
```
feat(websocket): add automatic reconnection with exponential backoff

Implements automatic reconnection when WebSocket connection drops.
Uses exponential backoff strategy with configurable max retries.

Closes #123
```

## Release Process

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Create release tag
4. Push to main branch
5. GitHub Actions will handle PyPI publishing

## Questions?

Feel free to open an issue for any questions or clarifications.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
