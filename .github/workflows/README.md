# GitHub Actions Workflows

This project contains two GitHub Actions workflows:

## 1. CI Workflow (`ci.yml`)

Used for continuous integration testing, automatically runs on every push to main/develop branches or when creating Pull Requests.

**Features:**
- Run tests on multiple operating systems (Linux, macOS, Windows)
- Support Python 3.10, 3.11, 3.12
- Code formatting checks (black, isort)
- Code quality checks (flake8)
- Type checking (mypy)

**Triggers:**
- Push to `main` or `develop` branch
- Create Pull Request to `main` or `develop` branch

## 2. Build Workflow (`build.yml`)

Used for building PyInstaller binaries, supports multi-platform builds.

**Features:**
- Build single executable files on Linux, macOS, Windows
- Automatically test built binaries
- Create GitHub Release (when pushing tags)
- Generate SHA256 checksums

**Triggers:**
- Push tags starting with `v` (e.g., `v0.1.3`)
- Manual trigger (workflow_dispatch)

### Usage

#### Automatic Build and Release

1. **Create and push a tag:**
   ```bash
   git tag v0.1.3
   git push origin v0.1.3
   ```

2. **GitHub Actions will automatically:**
   - Build binaries on three platforms
   - Test each binary
   - Create GitHub Release
   - Upload all binaries and checksums

#### Manual Trigger

1. Go to the GitHub repository's Actions page
2. Select "Build PyInstaller Binaries" workflow
3. Click "Run workflow"
4. Optionally enter a version number

### Build Artifacts

After building, you can find binaries in the following locations:

- **Artifacts**: Download from GitHub Actions run page
- **Releases**: If a tag was pushed, a release will be automatically created on GitHub Releases page

### Binary File Naming

- Linux: `castrel-proxy-linux-x86_64`
- macOS: `castrel-proxy-macos-x86_64`
- Windows: `castrel-proxy-windows-x86_64.exe`

### Local Build

If you want to build locally, you can use the following commands:

```bash
# Install dependencies
uv sync --all-extras

# Install PyInstaller
uv pip install pyinstaller

# Create entry script (resolves relative import issues)
cat > entry_point.py << 'EOF'
#!/usr/bin/env python
"""Entry point for PyInstaller - uses absolute imports"""
from castrel_proxy.cli.commands import run
if __name__ == "__main__":
    run()
EOF

# Build
uv run pyinstaller \
  --onefile \
  --name castrel-proxy \
  --paths src \
  --hidden-import castrel_proxy.data \
  --hidden-import castrel_proxy.cli.commands \
  --hidden-import typer \
  --hidden-import aiohttp \
  --hidden-import mcp \
  --hidden-import langchain_mcp_adapters \
  --hidden-import file_read_backwards \
  --console \
  --collect-all castrel_proxy \
  entry_point.py

# Binary files will be in dist/ directory
```

### Troubleshooting

If the build fails, check:

1. **Dependency issues**: Ensure all dependencies are correctly installed
2. **Hidden imports**: If you encounter `ModuleNotFoundError` at runtime, you may need to add `--hidden-import`
3. **Resource files**: Ensure using `importlib.resources` to access package data files (already fixed)

### Notes

- Building takes some time, especially on Windows
- Make sure to update the version number in `pyproject.toml` before pushing a tag
- Release will automatically extract version number from tag name (removing `v` prefix)
